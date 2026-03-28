"""
claude_agent.py — Harness Agent: Claude CLI + 多窗口编排 + 项目管理

DROP-IN REPLACEMENT — 直接替换你的 claude-tg-bot/claude_agent.py
AUTO-UPDATES from GitHub on every bot startup.

Architecture:
  User (Telegram) → bot.py → claude_agent.py → claude -p --resume <session>
                                                  ↓
                                              Full computer access + Harness Skills
                                              Uses Plan tokens (free)
                                              Persistent conversations
"""
import asyncio
import hashlib
import json
import logging
import os
import shutil
import signal
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
import config

logger = logging.getLogger(__name__)

# ─── AUTO-UPDATE ON STARTUP ─────────────────────────────────────────────────
# Every time this module loads (= bot starts), check GitHub for newer version.
# If found, replace self, clear __pycache__, and restart the bot process.

_GITHUB_RAW_URL = (
    "https://raw.githubusercontent.com/kdyz1205/multi-agent-coordinate-"
    "/main/tg_bot_integration/claude_agent_patched.py"
)
_THIS_FILE = Path(__file__).resolve()
_UPDATE_LOCK = _THIS_FILE.parent / ".update_lock"


def _self_update():
    """Check GitHub for a newer version and hot-replace if found."""
    try:
        # Skip if we updated less than 60s ago (prevent restart loops)
        if _UPDATE_LOCK.exists():
            lock_age = time.time() - _UPDATE_LOCK.stat().st_mtime
            if lock_age < 60:
                logger.debug(f"Skipping update check (last update {lock_age:.0f}s ago)")
                return False

        # Download latest from GitHub (cache-bust)
        url = f"{_GITHUB_RAW_URL}?t={int(time.time())}"
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            remote_content = resp.read()

        # Compare with current file
        local_content = _THIS_FILE.read_bytes()
        if hashlib.sha256(remote_content).digest() == hashlib.sha256(local_content).digest():
            logger.info("Auto-update: already up to date.")
            return False

        # Different! Replace self
        logger.warning("Auto-update: NEW VERSION found on GitHub, updating...")

        # Write new version
        _THIS_FILE.write_bytes(remote_content)

        # Clear __pycache__ so Python loads the new .py, not stale .pyc
        pycache = _THIS_FILE.parent / "__pycache__"
        if pycache.exists():
            shutil.rmtree(pycache, ignore_errors=True)

        # Write lock to prevent restart loops
        _UPDATE_LOCK.write_text(str(time.time()), encoding="utf-8")

        logger.warning(f"Auto-update: replaced {_THIS_FILE.name} ({len(remote_content)} bytes)")
        logger.warning("Auto-update: restarting bot process...")

        # Restart the entire bot process (exec replaces current process)
        os.execv(sys.executable, [sys.executable] + sys.argv)
        # ↑ This line never returns — process is replaced

    except (urllib.error.URLError, OSError) as e:
        # Network error / offline — skip silently, use current version
        logger.debug(f"Auto-update: network unavailable ({e})")
        return False
    except Exception as e:
        logger.warning(f"Auto-update: failed ({e}), continuing with current version")
        return False


# Run auto-update on module load (= bot startup)
_self_update()

# ─── CRITICAL: Strip ANTHROPIC_API_KEY from environment ─────────────────────
# config.py calls load_dotenv() which injects ANTHROPIC_API_KEY into os.environ.
# Claude CLI prioritizes API key over OAuth subscription.
# If the key has no credits → "Credit balance is too low" error.
# We MUST remove it so CLI falls back to OAuth (Max subscription = free).
_stripped_key = os.environ.pop("ANTHROPIC_API_KEY", None)
if _stripped_key:
    logger.warning(
        "Stripped ANTHROPIC_API_KEY from environment! "
        "CLI will use OAuth subscription instead (no API costs)."
    )

# Full path to claude CLI (npm global install)
CLAUDE_CMD = os.path.join(
    os.path.expanduser("~"), "AppData", "Roaming", "npm", "claude.cmd"
)

# Bot project directory (for self-awareness)
BOT_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# User home directory (default working directory for commands)
USER_HOME = os.path.expanduser("~")

# ─── System Prompt → saved to file, loaded via --append-system-prompt-file ──
# On Windows, --append-system-prompt with long strings breaks because .cmd
# files go through cmd.exe which corrupts special chars. Instead, write to
# a file and use --append-system-prompt-file which reads from disk.

_SYSTEM_PROMPT = f"""## RULES
1. NEVER just describe what you COULD do. USE TOOLS AND DO IT.
2. NEVER ask questions. JUST DO IT.
3. NEVER say you lack context. INFER and ACT.
4. Every response MUST include at least one tool use (shell, screenshot, file, browser).
5. If user says anything about a project → TAKE ACTION, don't just talk.

## WHO YOU ARE
TG bot on Windows 11. User controls you from phone via Telegram.
You have FULL computer access: shell, files, screenshot, mouse, keyboard, browser.
Your code: {BOT_PROJECT_DIR}

## CRITICAL: ALWAYS USE TOOLS
- User says "截图" → use screenshot tool NOW, then describe
- User says "列出项目" → run `dir /b /ad "%USERPROFILE%\\.claude\\projects\\"` NOW
- User says "继续xx项目" or "跟session对话" → DO THIS:
  1. screenshot (看桌面)
  2. If Claude Code window visible → mouse click on it → keyboard type the task → press Enter
  3. If no Claude Code window → run `cd PROJECT_DIR && claude` to open one
  4. Wait, screenshot again, summarize result
- User says "修复bug" → read the code files, find bugs, fix them NOW
- User says "打开浏览器" → run `start chrome --new-window "URL"` NOW

## MODE 2: Control Desktop Claude Code Sessions
When user says "继续项目"/"跟session说"/"帮我跟Claude Code说":
1. FIRST: take a screenshot to see desktop
2. LOOK for Claude Code windows (dark terminal with Claude logo)
3. If found: click on window → click input area → type the instruction → press Enter
4. Wait 10-15 seconds, screenshot again to check progress
5. When output stops changing → screenshot final result → summarize in Chinese → send to Telegram
6. If NO Claude Code window found: tell user, offer to open new session

## LOOP MINDSET — Act like a human
When given a task, work like a real person would:
1. DO the action (open app, click, type, run command)
2. OBSERVE the result (screenshot, read output)
3. If error/bug → FIX it and try again
4. REPEAT until it works perfectly
5. Never give up after one try. Try at least 3 different approaches.

Example: "去smartchain继续修bug"
→ screenshot desktop → find project folder → cd to it → read code → find bugs
→ fix code → run tests → screenshot result → if tests fail → fix again → repeat
→ when done, summarize what you fixed

Example: "打开网站测试UI"
→ start chrome → screenshot → click buttons → screenshot → check for errors
→ if error → read console → fix code → refresh → test again → repeat

## RESPONSE STYLE
- Be concise (user on phone)
- Reply in user's language (Chinese if they use Chinese)
- Show what you DID, not what you COULD do
- NEVER just list capabilities. DO THE WORK.
"""

# Write system prompt to file (read by CLI via --append-system-prompt-file)
_PROMPT_FILE = Path(BOT_PROJECT_DIR) / ".system_prompt.txt"
try:
    _PROMPT_FILE.write_text(_SYSTEM_PROMPT, encoding="utf-8")
    logger.info(f"System prompt written to {_PROMPT_FILE} ({_PROMPT_FILE.stat().st_size} bytes)")
except Exception as e:
    # If this fails, CLI will error with "file not found" — log loudly
    logger.error(f"CRITICAL: Failed to write system prompt file: {e}")
    # Try fallback location in temp dir
    import tempfile
    _PROMPT_FILE = Path(tempfile.gettempdir()) / "claude_bot_system_prompt.txt"
    try:
        _PROMPT_FILE.write_text(_SYSTEM_PROMPT, encoding="utf-8")
        logger.info(f"System prompt written to fallback: {_PROMPT_FILE}")
    except Exception as e2:
        logger.error(f"CRITICAL: Fallback also failed: {e2}")

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
    # Use setdefault for atomicity — prevents race where two coroutines
    # both see the key missing and create separate Lock objects
    return _processing_locks.setdefault(chat_id, asyncio.Lock())


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


# ─── Process Cleanup (Windows-safe) ──────────────────────────────────────────

async def _kill_process_tree(proc):
    """Kill a process and all its children. On Windows, proc.kill() only kills
    the .cmd wrapper — the actual node process keeps running as an orphan.
    Use taskkill /T /F to kill the entire process tree."""
    try:
        if os.name == "nt":
            # taskkill /T = kill tree, /F = force
            await asyncio.create_subprocess_exec(
                "taskkill", "/T", "/F", "/PID", str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        await proc.wait()
    except Exception as e:
        logger.debug(f"Process cleanup error (non-fatal): {e}")
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass


# ─── Known Error Patterns ────────────────────────────────────────────────────

_ERROR_PATTERNS = {
    "auth": [
        "not logged in",
        "please run /login",
    ],
    "credit": [
        "credit balance is too low",
        "credit balance",
        "insufficient credits",
        "billing",
    ],
    "rate_limit": [
        "hit your limit",
        "rate limit",
        "rate_limit",
        "too many requests",
    ],
}


def _detect_error(text: str) -> tuple[str | None, str | None]:
    """Check text for known error patterns. Returns (error_type, user_message) or (None, None)."""
    if not text:
        return None, None
    lower = text.lower()

    for pattern in _ERROR_PATTERNS["auth"]:
        if pattern in lower:
            return "auth", (
                "❌ Claude CLI 未登录！\n\n"
                "请在电脑上打开 PowerShell 运行：\n"
                "  claude /login\n\n"
                "选择 1 (Claude subscription)，完成浏览器登录后重启 bot。"
            )

    for pattern in _ERROR_PATTERNS["credit"]:
        if pattern in lower:
            return "credit", (
                "❌ API Key 余额不足！\n\n"
                "Bot 应该用 OAuth 订阅，不是 API Key。\n"
                "请检查 .env 文件，注释掉 ANTHROPIC_API_KEY：\n"
                "  # ANTHROPIC_API_KEY=sk-ant-...\n\n"
                "然后重启 bot。"
            )

    for pattern in _ERROR_PATTERNS["rate_limit"]:
        if pattern in lower:
            return "rate_limit", "⏳ Claude 达到速率限制。请稍等几分钟后再试。"

    return None, None


# ─── Claude CLI Runner ────────────────────────────────────────────────────────

async def _run_claude_cli(
    user_message: str, chat_id: int, context,
    timeout: int = None,
) -> tuple[str, str | None]:
    """Run claude CLI and return (response_text, session_id)."""
    timeout = timeout or getattr(config, "CLAUDE_CLI_TIMEOUT", 1800)  # 30 min for complex tasks
    session_id = _claude_sessions.get(chat_id)

    user_message = f"[TG bot msg] {user_message}"

    args = [
        CLAUDE_CMD,
        "-p", user_message,
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--model", config.CLAUDE_MODEL,
        "--append-system-prompt-file", str(_PROMPT_FILE),
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
        # Build clean environment — strip ANTHROPIC_API_KEY to force OAuth
        clean_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=USER_HOME,
            env=clean_env,
        )

        stdout_data, stderr_data = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )

    except asyncio.TimeoutError:
        logger.warning(f"Claude CLI timed out after {timeout}s")
        if proc is not None:
            await _kill_process_tree(proc)
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
    err_text = stderr_data.decode("utf-8", errors="replace").strip() if stderr_data else ""
    new_session_id = None
    response = None

    if err_text:
        logger.debug(f"Claude CLI stderr (chat {chat_id}): {err_text[:500]}")

    # ── Check stderr for known errors FIRST (often more reliable than stdout) ──
    err_type, err_msg = _detect_error(err_text)
    if err_type:
        logger.error(f"Claude CLI {err_type} error detected in stderr")
        return err_msg, None

    # ── Parse stdout JSON ──
    if raw:
        # Claude CLI may output warnings/progress before the JSON.
        # Find the LAST complete JSON object (not the first — first may be in a warning).
        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Find last '{' that starts a valid JSON object
            last_good_start = -1
            for i in range(len(raw) - 1, -1, -1):
                if raw[i] == '{':
                    try:
                        data = json.loads(raw[i:])
                        last_good_start = i
                        break
                    except json.JSONDecodeError:
                        continue
            if last_good_start == -1:
                # No valid JSON found — use raw text
                response = raw

        if data is not None:
            response = data.get("result", "").strip()
            new_session_id = data.get("session_id")

            if not response:
                if data.get("is_error"):
                    response = f"Error: {data.get('error', 'Unknown error')}"
                else:
                    response = "✅ 任务已执行（无文字输出）。"

    # ── Check stdout response for known errors ──
    if response:
        err_type, err_msg = _detect_error(response)
        if err_type:
            logger.error(f"Claude CLI {err_type} error detected in response")
            return err_msg, None  # Don't save session on error

    # ── Fallback if no stdout ──
    if not response:
        if err_text:
            logger.error(f"Claude CLI stderr: {err_text[:500]}")
            if "error" in err_text.lower():
                response = f"⚠️ {err_text[:500]}"
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
                await _send_response(chat_id, "⏰ 追加任务超时(30分钟)。发新消息继续。", context)
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
            "⏰ 任务处理超时(30分钟)。可能仍在后台运行。发新消息继续。",
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
    """Process a user message — CLI only, no API fallback."""
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
        # ONLY Claude CLI — no API fallback (no money spent)
        success = await _process_with_claude_cli(user_message, chat_id, context)
        if not success:
            await _send_response(chat_id, "⚠️ Claude CLI 失败，请重试。", context)


def clear_history(chat_id: int):
    """Clear all state for a chat."""
    conversations.pop(chat_id, None)
    _claude_sessions.pop(chat_id, None)
    _save_sessions()
    _pending_messages.pop(chat_id, None)
