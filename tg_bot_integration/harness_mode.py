"""
harness_mode.py — Alternative entry point (if you want a separate processing path).

For most users: Just use harness_prompt.py to enhance your existing system prompt.
That's simpler and avoids duplicate Claude CLI calls.

This file is for advanced use:
- If you want harness to be a SEPARATE processing path (not merged into Bridge mode)
- If you want different system prompts for different modes
- If you want harness-specific session tracking

Most users should use harness_prompt.py instead. See INSTALL.md.
"""

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Import the harness prompt enhancement
try:
    from harness_prompt import HARNESS_ENHANCEMENT
except ImportError:
    HARNESS_ENHANCEMENT = ""


# ─── Session Tracking ────────────────────────────────────────────────────────

SESSION_FILE = Path(__file__).parent / ".harness_sessions.json"


def _load_sessions() -> dict:
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_sessions(sessions: dict):
    try:
        SESSION_FILE.write_text(json.dumps(sessions, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save sessions: {e}")


# ─── Claude CLI Detection ────────────────────────────────────────────────────

def _get_claude_cmd() -> str:
    """Find claude CLI command."""
    for cmd in ["claude.cmd", "claude.exe", "claude"]:
        try:
            result = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return "claude"


# ─── Main Processing ─────────────────────────────────────────────────────────

async def process_with_harness(
    user_message: str,
    chat_id: int,
    context,
    send_response=None,
) -> bool:
    """
    Process a message via Claude CLI with Harness Agent system prompt.

    This is an ALTERNATIVE to the standard Bridge mode flow.
    The difference: this uses HARNESS_ENHANCEMENT as the system prompt,
    giving Claude multi-window orchestration capabilities.

    Returns True if successful, False to fall back.
    """

    async def _send(text: str):
        if not text:
            return
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            if send_response:
                await send_response(chat_id, chunk, context)
            else:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=chunk)
                except Exception as e:
                    logger.error(f"Failed to send: {e}")

    try:
        claude_cmd = _get_claude_cmd()
        sessions = _load_sessions()
        session_id = sessions.get(str(chat_id), {}).get("session_id")

        # Build command — same as your existing _run_claude_cli but with harness prompt
        cmd = [claude_cmd, "-p", "--output-format", "json"]

        if HARNESS_ENHANCEMENT:
            cmd.extend(["--append-system-prompt", HARNESS_ENHANCEMENT])

        if session_id:
            cmd.extend(["--resume", session_id])

        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass

        # Run Claude CLI asynchronously
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_data, stderr_data = await asyncio.wait_for(
            proc.communicate(input=user_message.encode("utf-8")),
            timeout=300,
        )

        # Parse response
        raw = stdout_data.decode("utf-8", errors="replace").strip()
        response = ""
        new_session_id = None

        if raw:
            try:
                data = json.loads(raw)
                response = data.get("result", "").strip()
                new_session_id = data.get("session_id")
            except json.JSONDecodeError:
                response = raw

        if not response:
            err = stderr_data.decode("utf-8", errors="replace").strip() if stderr_data else ""
            if err:
                response = f"⚠️ {err[:500]}"
            else:
                response = "✅ 任务已执行（无输出）。"

        # Save session for continuity
        if new_session_id:
            sessions[str(chat_id)] = {
                "session_id": new_session_id,
                "updated_at": time.time(),
            }
            _save_sessions(sessions)

        await _send(response)
        return True

    except asyncio.TimeoutError:
        await _send("⏰ 任务超时(5分钟)。可能仍在运行。")
        return True

    except FileNotFoundError:
        await _send("❌ Claude CLI 未找到。请安装: npm install -g @anthropic-ai/claude-code")
        return False

    except Exception as e:
        logger.error(f"Harness error: {e}", exc_info=True)
        await _send(f"⚠️ 错误: {str(e)[:300]}")
        return False


# ─── Commands ─────────────────────────────────────────────────────────────────

def clear_session(chat_id: int):
    sessions = _load_sessions()
    sessions.pop(str(chat_id), None)
    _save_sessions(sessions)


def get_harness_status() -> str:
    sessions = _load_sessions()
    lines = [
        "🤖 Harness Agent",
        "─" * 25,
        "模式: Claude CLI + 编排增强",
        f"活跃对话: {len(sessions)} 个",
        "",
        "用法: 直接发消息。",
        "Bot 自己判断是回答、写代码、还是开多窗口。",
    ]
    return "\n".join(lines)


def get_quota_status() -> str:
    try:
        from quota_tracker import QuotaTracker
        return QuotaTracker().status_report()
    except ImportError:
        return "Quota tracker 未安装。"
