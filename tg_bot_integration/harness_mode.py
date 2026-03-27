"""
harness_mode.py — Third processing mode for the Telegram bot.

DROP THIS FILE into your claude-tg-bot/ directory.

Architecture:
  User (Telegram) → bot.py → claude_agent.py → harness_mode.py
                                                    ↓
                                              Dispatcher (classify difficulty)
                                                    ↓
                                              Browser Automation
                                              → Opens AI web pages
                                              → Pastes prompt
                                              → Extracts response
                                                    ↓
                                              Result → Telegram

Cost: $0.00 (uses your existing AI subscriptions via browser)

Integration with existing bot:
  - Bridge mode (Plan tokens) = first choice
  - Harness mode (browser) = second choice (when Bridge rate-limited)
  - API mode (tokens) = last resort
"""

import asyncio
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── Lazy imports (only load when harness mode is actually used) ─────────────

_web_ai = None
_quota = None

def _get_web_ai():
    global _web_ai
    if _web_ai is None:
        from web_ai import WebAIRouter
        _web_ai = WebAIRouter()
    return _web_ai

def _get_quota():
    global _quota
    if _quota is None:
        from quota_tracker import QuotaTracker
        _quota = QuotaTracker()
    return _quota


# ─── Main Processing Function ───────────────────────────────────────────────

async def process_with_harness(
    user_message: str,
    chat_id: int,
    context,
    send_response=None,
) -> bool:
    """
    Process a message using browser automation on free AI web interfaces.

    Returns True if successful, False to fall back to API mode.

    Flow:
    1. Classify task difficulty
    2. Pick best available platform (quota-aware)
    3. Open browser → navigate to AI → paste prompt → wait → extract
    4. Send result back to Telegram
    """
    quota = _get_quota()
    web_ai = _get_web_ai()

    # Helper to send messages back to Telegram
    async def _send(text: str):
        if send_response:
            await send_response(chat_id, text, context)
        else:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                logger.error(f"Failed to send message: {e}")

    try:
        # Step 1: Classify and route
        platform, difficulty = web_ai.classify_and_route(user_message)

        # Step 2: Check quota
        if not quota.is_available(platform):
            # Try fallback
            fallback = quota.get_best_available()
            if fallback:
                await _send(
                    f"⚡ {platform} 用量已满，切换到 {fallback}"
                )
                platform = fallback
            else:
                # All exhausted — report wait time
                wait = quota.next_available_in()
                wait_min = int(wait / 60)
                await _send(
                    f"⏳ 所有平台用量已满。最快 {wait_min} 分钟后恢复。\n"
                    f"发 /quota 查看详情。"
                )
                return False  # Fall back to API mode

        # Step 3: Notify user
        await _send(f"🌐 Harness → {platform} (Level {difficulty})")
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Step 4: Execute via browser
        result = await web_ai.execute(platform, user_message)

        # Step 5: Record usage
        quota.record(platform, rate_limited=result.get("rate_limited", False))

        # Step 6: Send result
        if result["success"]:
            response = result["text"]
            if not response:
                response = "✅ 任务已执行（无文字输出）。"
            await _send(response)

            # If there are code blocks, send them separately for easy copying
            for i, code in enumerate(result.get("code_blocks", [])):
                if code.strip():
                    await _send(f"```\n{code[:3500]}\n```")

            return True
        else:
            error = result.get("error", "Unknown error")
            if "rate limit" in error.lower() or result.get("rate_limited"):
                quota.record(platform, rate_limited=True)
                await _send(
                    f"⏳ {platform} 达到限制。"
                )
                # Try another platform
                fallback = quota.get_best_available()
                if fallback and fallback != platform:
                    await _send(f"🔄 切换到 {fallback} 重试...")
                    result2 = await web_ai.execute(fallback, user_message)
                    quota.record(fallback, rate_limited=result2.get("rate_limited", False))
                    if result2["success"]:
                        await _send(result2["text"])
                        return True

                return False  # Fall back to API

            await _send(f"⚠️ Harness 错误: {error[:300]}")
            return False

    except Exception as e:
        logger.error(f"Harness mode error: {e}", exc_info=True)
        await _send(f"⚠️ Harness 出错: {str(e)[:300]}")
        return False


# ─── Status & Commands ───────────────────────────────────────────────────────

def get_quota_status() -> str:
    """Get quota status for /quota command."""
    return _get_quota().status_report()


def get_harness_status() -> str:
    """Get harness status for /status command."""
    quota = _get_quota()
    available = quota.get_all_available()
    exhausted = quota.get_all_exhausted()

    lines = [
        "🌐 Harness 状态",
        "─" * 30,
        f"可用平台: {', '.join(available) if available else '无'}",
        f"已满平台: {', '.join(exhausted) if exhausted else '无'}",
    ]

    if exhausted:
        for p in exhausted:
            wait = quota.time_until_available(p)
            lines.append(f"  {p}: {int(wait/60)}分钟后恢复")

    return "\n".join(lines)
