"""
harness_mode.py — PRIMARY processing mode for the Telegram bot.

DROP THIS FILE into your claude-tg-bot/ directory.

Architecture (Harness-First):
  User (Telegram) → bot.py → claude_agent.py → harness_mode.py
                                                    ↓
                                              1. "需要操控电脑?" 检测
                                                    ↓
                                    ┌─ YES → Claude CLI (唯一有工具的)
                                    └─ NO  → Dispatcher (classify difficulty)
                                                    ↓
                                              ┌─ Level 1 (Q&A) → Grok / GPT
                                              ├─ Level 2 (单文件) → Claude Web
                                              ├─ Level 3 (重度代码) → Claude Code Web
                                              └─ Level 4-5 (多文件) → 多平台并行 + Git合并
                                                    ↓
                                              Result → Telegram

Cost: $0.00 (uses your existing AI subscriptions via browser)

Routing priority:
  ★ Harness Mode (browser) = PRIMARY (free, multi-platform)
  Claude CLI              = ONLY when task needs computer control
  API Mode (tokens)       = LAST resort (all platforms exhausted)
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# ─── Lazy imports ────────────────────────────────────────────────────────────

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


# ─── Computer Control Detection ─────────────────────────────────────────────
# These keywords indicate the task requires actual computer control
# (mouse, keyboard, file system, apps) — ONLY these go to Claude CLI.

COMPUTER_CONTROL_KEYWORDS_ZH = [
    "打开", "截图", "截屏", "鼠标", "键盘", "点击", "右键",
    "文件管理", "打开文件", "运行程序", "桌面", "窗口",
    "复制文件", "移动文件", "删除文件", "安装软件", "安装程序",
    "终端", "命令行", "打开浏览器", "打开app", "打开应用",
    "屏幕", "录屏", "拖拽", "剪贴板", "系统设置",
    "打开vscode", "打开编辑器", "保存文件",
]

COMPUTER_CONTROL_KEYWORDS_EN = [
    "screenshot", "open app", "open file", "open browser", "open vscode",
    "click", "right click", "mouse", "keyboard", "drag",
    "clipboard", "terminal", "desktop", "window",
    "move file", "copy file", "delete file", "rename file",
    "install", "run command", "execute", "launch",
    "take a screenshot", "screen recording", "system settings",
    "file manager", "task manager", "finder",
]

# Patterns that strongly indicate computer control
COMPUTER_CONTROL_PATTERNS = [
    r"帮我打开",
    r"帮我安装",
    r"帮我运行",
    r"帮我截",
    r"open\s+\w+\s+app",
    r"run\s+\w+\s+command",
    r"take\s+a?\s*screenshot",
    r"在我的?电脑",
    r"在本地",
    r"on my (?:computer|desktop|machine)",
]


def needs_computer_control(message: str) -> bool:
    """
    Detect if a task requires actual computer control (mouse/keyboard/files/apps).

    Only tasks that need physical computer interaction should go to Claude CLI.
    Everything else (coding, Q&A, analysis) goes to free web AI platforms.

    Returns True → route to Claude CLI
    Returns False → route to web AI (free)
    """
    msg_lower = message.lower()

    # Check Chinese keywords
    for kw in COMPUTER_CONTROL_KEYWORDS_ZH:
        if kw in msg_lower:
            return True

    # Check English keywords
    for kw in COMPUTER_CONTROL_KEYWORDS_EN:
        if kw in msg_lower:
            return True

    # Check regex patterns
    import re
    for pattern in COMPUTER_CONTROL_PATTERNS:
        if re.search(pattern, msg_lower):
            return True

    return False


# ─── Main Processing Function ────────────────────────────────────────────────

async def process_with_harness(
    user_message: str,
    chat_id: int,
    context,
    send_response=None,
    cli_fallback=None,
) -> bool:
    """
    PRIMARY message processor. Routes to free web AI or Claude CLI.

    Returns True if successful, False to fall back to API mode.

    Flow:
    1. Check if task needs computer control → Claude CLI
    2. Classify task difficulty (Level 1-5)
    3. Pick best available platform(s) — quota-aware
    4. Execute via browser automation (parallel if multi-platform)
    5. Send result back to Telegram

    Args:
        user_message: The user's message text
        chat_id: Telegram chat ID
        context: Telegram context object
        send_response: Optional custom send function
        cli_fallback: Optional async function to call Claude CLI for computer control tasks
    """
    quota = _get_quota()
    web_ai = _get_web_ai()

    # Helper to send messages back to Telegram
    async def _send(text: str):
        if not text:
            return
        # Telegram message limit is 4096 chars
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            if send_response:
                await send_response(chat_id, chunk, context)
            else:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=chunk)
                except Exception as e:
                    logger.error(f"Failed to send message: {e}")

    try:
        # ── Step 0: Computer control check ──────────────────────────────
        if needs_computer_control(user_message):
            await _send("🖥️ 检测到需要操控电脑 → Claude CLI")

            if cli_fallback:
                success = await cli_fallback(user_message, chat_id, context)
                if success:
                    return True
                await _send("⚠️ CLI 执行失败，尝试浏览器模式...")
                # Fall through to web AI as backup
            else:
                # No CLI fallback available — tell user
                await _send(
                    "⚠️ 此任务需要操控电脑（截图/打开文件等），"
                    "但 Claude CLI 未连接。\n"
                    "请确保 Bridge Mode 可用，或改用不需要操控电脑的方式描述任务。"
                )
                return False

        # ── Step 1: Classify and route ──────────────────────────────────
        route = web_ai.classify_and_route(user_message)
        platform = route["platform"]
        difficulty = route["difficulty"]
        is_parallel = route["parallel"]
        subtasks = route.get("subtasks", [])

        # ── Step 2: Check quota ─────────────────────────────────────────
        if not quota.is_available(platform):
            fallback = quota.get_best_available()
            if fallback:
                await _send(f"⚡ {platform} 用量已满，切换到 {fallback}")
                platform = fallback
            else:
                wait = quota.next_available_in()
                wait_min = max(1, int(wait / 60))
                await _send(
                    f"⏳ 所有平台用量已满。最快 {wait_min} 分钟后恢复。\n"
                    f"发 /quota 查看详情。"
                )
                return False  # Fall back to API mode

        # ── Step 3: Notify user ─────────────────────────────────────────
        if is_parallel and len(subtasks) > 1:
            platforms_str = ", ".join(s["platform"] for s in subtasks)
            await _send(
                f"🌐 Level {difficulty} → 多平台并行分发\n"
                f"平台: {platforms_str}\n"
                f"子任务: {len(subtasks)} 个"
            )
        else:
            await _send(f"🌐 Harness → {platform} (Level {difficulty})")

        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass

        # ── Step 4: Execute ─────────────────────────────────────────────
        if is_parallel and len(subtasks) > 1:
            # Parallel multi-platform execution
            result = await _execute_parallel(web_ai, quota, subtasks, _send)
        else:
            # Single platform execution
            result = await web_ai.execute(platform, user_message)
            quota.record(platform, rate_limited=result.get("rate_limited", False))

        # ── Step 5: Send result ─────────────────────────────────────────
        if result["success"]:
            response = result["text"]
            if not response:
                response = "✅ 任务已执行（无文字输出）。"
            await _send(response)

            # Send code blocks separately for easy copying
            for i, code in enumerate(result.get("code_blocks", [])):
                if code.strip():
                    await _send(f"```\n{code[:3500]}\n```")

            return True
        else:
            error = result.get("error", "Unknown error")

            # Rate limit handling with auto-retry on another platform
            if "rate limit" in error.lower() or result.get("rate_limited"):
                quota.record(platform, rate_limited=True)
                await _send(f"⏳ {platform} 达到限制。")

                fallback = quota.get_best_available()
                if fallback and fallback != platform:
                    await _send(f"🔄 切换到 {fallback} 重试...")
                    result2 = await web_ai.execute(fallback, user_message)
                    quota.record(fallback, rate_limited=result2.get("rate_limited", False))
                    if result2["success"]:
                        await _send(result2["text"])
                        for code in result2.get("code_blocks", []):
                            if code.strip():
                                await _send(f"```\n{code[:3500]}\n```")
                        return True

                return False  # Fall back to API

            await _send(f"⚠️ Harness 错误: {error[:300]}")
            return False

    except Exception as e:
        logger.error(f"Harness mode error: {e}", exc_info=True)
        await _send(f"⚠️ Harness 出错: {str(e)[:300]}")
        return False


async def _execute_parallel(web_ai, quota, subtasks: list[dict], _send) -> dict:
    """
    Execute multiple subtasks on different platforms in parallel.
    Collects results and merges them.
    """
    async def _run_one(subtask: dict) -> dict:
        platform = subtask["platform"]
        prompt = subtask["prompt"]
        try:
            result = await web_ai.execute(platform, prompt)
            quota.record(platform, rate_limited=result.get("rate_limited", False))

            # If this platform failed, try fallback
            if not result["success"] and result.get("rate_limited"):
                quota.record(platform, rate_limited=True)
                fallback = quota.get_best_available()
                if fallback:
                    await _send(f"🔄 {platform} 限流 → {fallback}")
                    result = await web_ai.execute(fallback, prompt)
                    quota.record(fallback, rate_limited=result.get("rate_limited", False))

            return {**result, "subtask": subtask.get("label", ""), "platform": platform}
        except Exception as e:
            return {
                "success": False, "text": "", "code_blocks": [],
                "rate_limited": False, "error": str(e),
                "subtask": subtask.get("label", ""), "platform": platform,
            }

    # Run all subtasks concurrently
    tasks = [_run_one(st) for st in subtasks]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge results
    all_text = []
    all_code = []
    any_success = False

    for i, res in enumerate(results):
        if isinstance(res, Exception):
            all_text.append(f"[子任务 {i+1} 失败: {str(res)[:100]}]")
            continue

        label = res.get("subtask", f"Part {i+1}")
        if res["success"]:
            any_success = True
            all_text.append(f"━━━ {label} ({res['platform']}) ━━━")
            all_text.append(res["text"])
            all_code.extend(res.get("code_blocks", []))
        else:
            all_text.append(f"[{label} 失败: {res.get('error', 'unknown')[:100]}]")

    return {
        "success": any_success,
        "text": "\n\n".join(all_text),
        "code_blocks": all_code,
        "rate_limited": False,
        "error": "" if any_success else "All subtasks failed",
        "duration": 0,
    }


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
        "🌐 Harness 状态 (PRIMARY MODE)",
        "─" * 30,
        "",
        "路由逻辑:",
        "  消息进来 → 检测是否需要操控电脑",
        "  ├─ 需要操控 → Claude CLI",
        "  └─ 不需要 → 免费网页AI (自动选择)",
        "",
        f"可用平台: {', '.join(available) if available else '无'}",
        f"已满平台: {', '.join(exhausted) if exhausted else '无'}",
    ]

    if exhausted:
        for p in exhausted:
            wait = quota.time_until_available(p)
            if wait > 0:
                lines.append(f"  {p}: {int(wait/60)}分钟后恢复")

    return "\n".join(lines)


def test_routing(message: str) -> str:
    """Test how a message would be routed (for debugging)."""
    web_ai = _get_web_ai()
    quota = _get_quota()

    is_cli = needs_computer_control(message)
    route = web_ai.classify_and_route(message)

    lines = [
        f"消息: {message[:80]}",
        f"需要操控电脑: {'是 → CLI' if is_cli else '否 → 网页AI'}",
        f"难度级别: Level {route['difficulty']}",
        f"目标平台: {route['platform']}",
        f"并行分发: {'是' if route['parallel'] else '否'}",
    ]

    if route["parallel"]:
        for st in route.get("subtasks", []):
            lines.append(f"  子任务: {st['label']} → {st['platform']}")

    lines.append("")
    lines.append(quota.status_report())
    return "\n".join(lines)
