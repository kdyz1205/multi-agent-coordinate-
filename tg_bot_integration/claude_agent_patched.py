"""
claude_agent.py — Harness Agent: Claude CLI + 多窗口编排 + 项目管理

PATCHED VERSION — 直接替换你的 claude-tg-bot/claude_agent.py

改了什么:
1. _SYSTEM_PROMPT 增加了 Harness 技能（多窗口、项目管理、截图、session管理）
2. 没有其他任何改动。路由、session、队列全部保持原样。

Architecture:
  User (Telegram) → bot.py → claude_agent.py → claude -p --resume <session>
                                                  ↓
                                              Full computer access + Harness Skills
                                              Uses Plan tokens (free)
                                              Persistent conversations
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
import config

logger = logging.getLogger(__name__)

# Full path to claude CLI (npm global install)
CLAUDE_CMD = os.path.join(
    os.path.expanduser("~"), "AppData", "Roaming", "npm", "claude.cmd"
)

# Bot project directory (for self-awareness)
BOT_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# User home directory (default working directory for commands)
USER_HOME = os.path.expanduser("~")

# ─── System Prompt ───────────────────────────────────────────────────────────
# Original rules + Harness Agent skills

_SYSTEM_PROMPT = f"""
## ⛔ RULES
1. NEVER ask questions. NEVER say "could you clarify"/"你能说得更具体吗". JUST DO IT.
2. NEVER say you lack context. INFER and ACT.
3. "fix bugs"/"修复bug" → read code at {BOT_PROJECT_DIR}, fix immediately.
4. "继续"/"continue" → continue previous task from context.
5. NEVER close/minimize user's existing browser windows. Open NEW windows only: `start chrome --new-window "URL"`
6. Don't output "Level X → Claude.ai". Just do the work silently.
7. Simple tasks → do yourself. Only open browser when genuinely needed (Gemini for images, parallel Claude Code sessions).

## WHO YOU ARE
TG bot (@damnthisiscrazybot) on Windows 11. User controls you from phone. You ARE Claude Code with full computer access.
Your code: {BOT_PROJECT_DIR} (bot.py, claude_agent.py, config.py, providers.py, tools.py, browser_agent.py)
GitHub: https://github.com/kdyz1205/claude-tg-bot

## BEHAVIOR
- ACT IMMEDIATELY. Be concise (user on phone). Reply in user's language.
- Full computer: files, apps, shell, browser, screenshot, mouse, keyboard.
- If fails, try alternatives silently. Never ask permission.

## HARNESS AGENT SKILLS

**项目管理**: "列出项目" → `dir /b /ad "%USERPROFILE%\\.claude\\projects\\"` 整理返回
**Session历史**: "看历史" → find .jsonl files in ~/.claude/projects/, read tail, summarize in Chinese
**继续项目**: "去xx项目继续" → cd到目录, 读代码, 直接修改. 或 `claude -p "task"` 新进程
**多进程并行**: 复杂任务 → 多个 `Start-Process claude -ArgumentList "-p","task" -WorkingDirectory "dir"` 并行
**浏览器AI**: 需要时 → `start chrome --new-window "URL"` → 截图→鼠标操控→提取结果
**截图**: "截图"/"给我看" → screenshot tool → 描述屏幕内容
"""

# ─── Session Persistence ─────────────────────────────────────────────────────

_SESSION_FILE = Path(__file__).parent / ".sessions.json"

def _load_sessions() -> dict[int, str]:
    """Load session IDs from disk so they survive bot restarts."""
    try:
        if _SESSION_FILE.exists():
            data = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
            return {int(k): v for k, v in data.items() if v}
    except Exception as e:
        logger.warning(f"Failed to load sessions: {e}")
    return {}

def _save_sessions():
    """Persist session IDs to disk."""
    try:
        _SESSION_FILE.write_text(
            json.dumps({str(k): v for k, v in _claude_sessions.items()}, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Failed to save sessions: {e}")

# ─── Session & Queue State ──────────────────────────────────────────────────

_claude_sessions: dict[int, str] = _load_sessions()
conversations: dict[int, list[dict]] = {}
_pending_messages: dict[int, list[dict]] = {}
_processing_locks: dict[int, asyncio.Lock] = {}
_MAX_PENDING_AGE = 600  # 10 minutes


def _get_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _processing_locks:
        _processing_locks[chat_id] = asyncio.Lock()
    return _processing_locks[chat_id]


# ─── Typing Indicator ────────────────────────────────────────────────────────

async def _keep_typing(chat_id, context, stop_event):
    """Send typing indicator every 4 seconds while processing."""
    while not stop_event.is_set():
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4)
            break
        except asyncio.TimeoutError:
            pass


# ─── Claude CLI Runner ────────────────────────────────────────────────────────

async def _run_claude_cli(
    user_message: str, chat_id: int, context,
    timeout: int = None,
) -> tuple[str, str | None]:
    """Run claude CLI and return (response_text, session_id)."""
    timeout = timeout or getattr(config, "CLAUDE_CLI_TIMEOUT", 300)
    session_id = _claude_sessions.get(chat_id)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _MSG_PREFIX = (
        f"[{now_str}] "
        f"[CONTEXT: You are a Telegram bot. Your code is at {BOT_PROJECT_DIR}. "
        f"NEVER ask questions. NEVER say you lack context. If user says 'fix bugs'/'修复bug' "
        f"→ read your own source code and fix things. JUST ACT.]\n\n"
    )
    user_message = _MSG_PREFIX + user_message

    args = [
        CLAUDE_CMD,
        "-p",
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--model", config.CLAUDE_MODEL,
        "--append-system-prompt", _SYSTEM_PROMPT,
    ]
    if session_id:
        args.extend(["--resume", session_id])
        logger.info(f"Chat {chat_id}: resuming session {session_id[:12]}... (model: {config.CLAUDE_MODEL})")
    else:
        logger.info(f"Chat {chat_id}: new session (model: {config.CLAUDE_MODEL})")

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(chat_id, context, stop_typing))
    proc = None

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=USER_HOME,
        )

        stdout_data, stderr_data = await asyncio.wait_for(
            proc.communicate(input=user_message.encode("utf-8")),
            timeout=timeout,
        )

    except asyncio.TimeoutError:
        logger.warning(f"Claude CLI timed out after {timeout}s")
        if proc is not None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        raise

    except FileNotFoundError:
        logger.error(f"Claude CLI not found at: {CLAUDE_CMD}")
        raise

    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass

    if proc.returncode != 0:
        logger.warning(f"Claude CLI exited with code {proc.returncode}")

    # Parse JSON response
    raw = stdout_data.decode("utf-8", errors="replace").strip()
    new_session_id = None
    response = None

    if raw:
        try:
            data = json.loads(raw)
            response = data.get("result", "").strip()
            new_session_id = data.get("session_id")

            if not response:
                if data.get("is_error"):
                    response = f"Error: {data.get('error', 'Unknown error')}"
                else:
                    response = "✅ 任务已执行（无文字输出）。"

            # Rate limit detection — don't store poisoned session
            if response and ("hit your limit" in response.lower() or "rate limit" in response.lower()):
                logger.warning(f"Claude CLI rate limited: {response[:200]}")
                response = "⏳ Claude 达到速率限制。请稍等几分钟后再试。"
                new_session_id = None

        except json.JSONDecodeError:
            json_start = raw.find('{')
            if json_start > 0:
                try:
                    data = json.loads(raw[json_start:])
                    response = data.get("result", "").strip()
                    new_session_id = data.get("session_id")
                    if not response:
                        response = raw[:json_start].strip() or "✅ 任务已执行。"
                except json.JSONDecodeError:
                    response = raw
            else:
                response = raw

    if stderr_data:
        err_text = stderr_data.decode("utf-8", errors="replace").strip()
        if err_text:
            logger.debug(f"Claude CLI stderr (chat {chat_id}): {err_text[:500]}")

    if not response:
        err = stderr_data.decode("utf-8", errors="replace").strip() if stderr_data else ""
        if err:
            logger.error(f"Claude CLI stderr: {err[:500]}")
            if "error" in err.lower():
                response = f"⚠️ {err[:500]}"
            else:
                response = "✅ 任务已执行。"
        else:
            response = "✅ 任务已执行（无输出）。"

    return response, new_session_id


# ─── Response Sender ──────────────────────────────────────────────────────────

async def _send_response(chat_id: int, response: str, context):
    """Send response to Telegram, splitting into chunks if needed."""
    if not response or not response.strip():
        return

    MAX_TOTAL = 16000
    if len(response) > MAX_TOTAL:
        response = response[:MAX_TOTAL] + "\n\n... (输出过长，已截断。需要完整内容请说。)"

    remaining = response
    while remaining:
        if len(remaining) <= 4000:
            chunk = remaining
            remaining = ""
        else:
            break_pos = remaining.rfind("\n", 3000, 4000)
            if break_pos == -1:
                break_pos = 4000
            chunk = remaining[:break_pos]
            remaining = remaining[break_pos:]

        try:
            await context.bot.send_message(
                chat_id=chat_id, text=chunk, parse_mode="Markdown"
            )
        except Exception:
            try:
                await context.bot.send_message(chat_id=chat_id, text=chunk)
            except Exception as e:
                logger.error(f"Failed to send message to {chat_id}: {e}")


# ─── Queue Helpers ────────────────────────────────────────────────────────────

def _drain_pending(chat_id: int) -> list[dict]:
    msgs = _pending_messages.pop(chat_id, [])
    now = time.time()
    fresh = [m for m in msgs if now - m["time"] < _MAX_PENDING_AGE]
    if len(fresh) < len(msgs):
        logger.info(f"Chat {chat_id}: dropped {len(msgs) - len(fresh)} stale queued messages")
    return fresh


def _queue_message(chat_id: int, text: str):
    if chat_id not in _pending_messages:
        _pending_messages[chat_id] = []
    _pending_messages[chat_id].append({
        "text": text,
        "time": time.time(),
    })


# ─── Main Processing Logic ────────────────────────────────────────────────────

async def _process_with_claude_cli(user_message: str, chat_id: int, context) -> bool:
    """Process message using Claude Code CLI. Returns True on success."""
    try:
        response, new_session_id = await _run_claude_cli(user_message, chat_id, context)

        # Session recovery: if response indicates session error, retry without resume
        resp_lower = response.lower() if response else ""
        if response and (
            ("session" in resp_lower and "error" in resp_lower)
            or "invalid session" in resp_lower
            or ("could not find" in resp_lower and "session" in resp_lower)
        ):
            logger.warning(f"Chat {chat_id}: session error detected, starting fresh")
            _claude_sessions.pop(chat_id, None)
            response, new_session_id = await _run_claude_cli(user_message, chat_id, context)

        if new_session_id:
            _claude_sessions[chat_id] = new_session_id
            _save_sessions()
            logger.info(f"Chat {chat_id}: session_id = {new_session_id[:12]}...")
        else:
            logger.debug(f"Chat {chat_id}: no session_id returned")

        await _send_response(chat_id, response, context)

        # Process queued follow-up messages
        pending = _drain_pending(chat_id)
        while pending:
            combined = "\n---\n".join(m["text"] for m in pending)
            count = len(pending)
            logger.info(f"Chat {chat_id}: processing {count} queued follow-up messages")

            await _send_response(chat_id, f"📨 处理你追加的 {count} 条消息...", context)

            try:
                followup_resp, followup_sid = await _run_claude_cli(combined, chat_id, context)
                if followup_sid:
                    _claude_sessions[chat_id] = followup_sid
                    _save_sessions()
                await _send_response(chat_id, followup_resp, context)
            except asyncio.TimeoutError:
                await _send_response(chat_id, "⏰ 追加任务超时(5分钟)。发新消息继续。", context)
                break
            except Exception as e:
                logger.error(f"Follow-up error: {e}", exc_info=True)
                await _send_response(chat_id, f"⚠️ 追加消息处理出错: {str(e)[:300]}", context)
                break

            pending = _drain_pending(chat_id)

        return True

    except asyncio.TimeoutError:
        await _send_response(
            chat_id,
            "⏰ 任务处理超时(5分钟)。可能仍在后台运行。发新消息继续。",
            context,
        )
        return True  # Don't fallback to API on timeout

    except FileNotFoundError:
        await _send_response(
            chat_id,
            "❌ Claude CLI 未找到。请运行: npm install -g @anthropic-ai/claude-code",
            context,
        )
        return False

    except Exception as e:
        logger.error(f"Claude CLI error: {e}", exc_info=True)
        await _send_response(chat_id, f"⚠️ Claude Code 出错: {str(e)[:500]}", context)
        return False


async def process_message(user_message: str, chat_id: int, context):
    """Process a user message — single path, no duplicate calls."""
    lock = _get_lock(chat_id)

    if lock.locked():
        _queue_message(chat_id, user_message)
        queue_size = len(_pending_messages.get(chat_id, []))
        logger.info(f"Chat {chat_id}: queued message ({queue_size} pending)")
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📝 收到 (第{queue_size}条追加)，处理完当前任务后会一起看。",
            )
        except Exception:
            pass
        return

    async with lock:
        # PRIMARY: Claude CLI with Harness Agent skills
        if getattr(config, "BRIDGE_MODE", True):
            success = await _process_with_claude_cli(user_message, chat_id, context)
            if success:
                return
            logger.warning("Claude CLI failed, falling back to API providers")

        # FALLBACK: API provider (costs money, last resort)
        try:
            from providers import process_with_auto_fallback

            if chat_id not in conversations:
                conversations[chat_id] = []

            history = conversations[chat_id]
            pending = _drain_pending(chat_id)
            if pending:
                combined = user_message + "\n" + "\n".join(m["text"] for m in pending)
            else:
                combined = user_message
            history.append({"role": "user", "content": combined})

            while len(history) > config.MAX_CONVERSATION_HISTORY:
                history.pop(0)

            success = await process_with_auto_fallback(history, chat_id, context)

            if not success:
                return

            conversations[chat_id] = [
                m for m in conversations[chat_id]
                if isinstance(m.get("content"), str)
            ]

        except Exception as e:
            logger.error(f"API fallback error: {e}", exc_info=True)
            await _send_response(chat_id, f"❌ 处理失败: {str(e)[:500]}", context)


def clear_history(chat_id: int):
    """Clear all state for a chat."""
    conversations.pop(chat_id, None)
    _claude_sessions.pop(chat_id, None)
    _save_sessions()
    _pending_messages.pop(chat_id, None)
