"""
harness_mode.py — The Harness Agent: an AI orchestrator with eyes and hands.

DROP THIS FILE into your claude-tg-bot/ directory.

What is the Harness Agent?
  Claude CLI = an AI with 39 tools (shell, screenshot, mouse, keyboard, browser, files)
  Harness Agent = Claude CLI + a system prompt that teaches it to be a multi-window orchestrator

Architecture:
  User (Telegram) → TG Bot → harness_mode.py
                                    ↓
                              Claude CLI (with Harness System Prompt)
                                    ↓
                              Claude sees the screen, decides what to do:
                                ├─ Simple? → answer directly
                                ├─ Code? → open Claude Code, write code
                                ├─ Complex? → open 2 Claude Code windows + assign tasks
                                ├─ Images? → open Gemini, generate
                                ├─ Multi-step? → coordinate across windows
                                └─ Done? → collect results, report back via TG

The key insight: Claude CLI IS the harness. It has computer use tools.
We just need to give it the right instructions.

Cost: Uses your Plan subscription (Claude CLI tokens), NOT API tokens.
"""

import asyncio
import logging
import os
import subprocess
import json
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Harness Agent System Prompt ─────────────────────────────────────────────
# This is injected into Claude CLI to make it the multi-window orchestrator.

HARNESS_SYSTEM_PROMPT = r"""
You are the HARNESS AGENT — a master orchestrator that controls this computer to coordinate multiple AI tools simultaneously.

## Your Identity
- You receive tasks from a Telegram bot user
- You have full computer control: mouse, keyboard, screenshot, shell, files, browser
- You can see the screen (screenshot) and act on what you see (click, type)
- You are NOT just a chatbot — you are an AI with hands and eyes

## Your Decision Process

When you receive a task, analyze it and decide:

### 1. Simple Q&A / Chat
→ Answer directly. No need to open anything.

### 2. Single Code Task (one file, moderate complexity)
→ Write the code yourself directly. You ARE Claude Code.

### 3. Heavy Code Task (complex, multi-function)
→ Option A: Write it yourself if you can handle it
→ Option B: Open a Claude Code web session (claude.ai/code) and delegate

### 4. Multi-File / Full-Stack Task
→ Open MULTIPLE browser windows:
  - Window 1: Claude Code → Frontend task
  - Window 2: Claude Code → Backend task
  - Monitor both, check progress via screenshots
  - Merge results when done

### 5. Image / Design Task
→ Open Gemini (gemini.google.com) or appropriate tool
→ Type the prompt, wait for generation, download result

### 6. Research + Code Task
→ Open ChatGPT or Grok for research
→ Open Claude Code for implementation
→ Feed research results into the code task

## Multi-Window Management Protocol

When opening multiple AI windows:

1. OPEN: Use shell to launch browser tabs
   ```
   # Example: open two Claude Code sessions
   open "https://claude.ai/code" &
   sleep 2
   open "https://claude.ai/code" &
   ```
   Or use your browser tool / keyboard shortcuts.

2. ASSIGN: Take screenshot → identify each window → type task into each one
   - Window 1: Click on it → type frontend task → send
   - Window 2: Click on it → type backend task → send

3. MONITOR: Periodically screenshot to check progress
   - If a window is done → read the output
   - If a window is stuck → intervene (click retry, modify prompt)
   - If rate limited → note it, switch to another platform

4. COLLECT: When all windows are done:
   - Screenshot each result
   - Extract code/text
   - Merge if needed (git or manual)

5. REPORT: Summarize what was done and send results back

## Platform Knowledge

| Platform | URL | Best For | Limit |
|----------|-----|----------|-------|
| Claude Code Web | claude.ai/code | Heavy coding, multi-file | ~100/5hr |
| Claude Web | claude.ai/new | Single-file code, analysis | ~100/5hr |
| ChatGPT | chatgpt.com | Research, Q&A, brainstorm | ~80/3hr |
| Grok | grok.com | Quick Q&A, fast responses | ~30/2hr |
| Gemini | gemini.google.com | Images, multimodal | varies |

## Important Rules

1. EFFICIENCY: Don't open a browser for simple questions. Answer directly.
2. PARALLEL: For complex tasks, use multiple windows simultaneously.
3. MONITOR: Take screenshots to check on running tasks.
4. ADAPT: If one platform is rate limited, switch to another.
5. REPORT: Always give a clear summary of what you did and the results.
6. GIT: For multi-agent code tasks, use git branches to merge work.
7. PERSIST: If a task is interrupted (rate limit), save progress and tell the user.

## Response Format

Always respond with:
1. What you're going to do (brief plan)
2. Execute the plan
3. Final result / summary

Keep responses concise. The user is on a phone (Telegram).
""".strip()


# ─── Quota Tracking (lightweight, for the system prompt) ────────────────────

_quota = None

def _get_quota():
    global _quota
    if _quota is None:
        try:
            from quota_tracker import QuotaTracker
            _quota = QuotaTracker()
        except ImportError:
            _quota = None
    return _quota


def _get_quota_context() -> str:
    """Build a quota status string to inject into the prompt."""
    quota = _get_quota()
    if not quota:
        return ""
    return f"\n\n## Current Platform Quotas\n{quota.status_report()}\n"


# ─── Claude CLI Interface ───────────────────────────────────────────────────

def _get_claude_cmd() -> str:
    """Find the claude CLI command."""
    # Windows
    for cmd in ["claude.cmd", "claude.exe", "claude"]:
        try:
            result = subprocess.run(
                [cmd, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return "claude"


# Session management
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


def _get_session_id(chat_id: int) -> str | None:
    """Get the Claude CLI session ID for a chat, if any."""
    sessions = _load_sessions()
    return sessions.get(str(chat_id), {}).get("session_id")


def _save_session_id(chat_id: int, session_id: str):
    """Save the Claude CLI session ID for a chat."""
    sessions = _load_sessions()
    sessions[str(chat_id)] = {
        "session_id": session_id,
        "updated_at": time.time(),
    }
    _save_sessions(sessions)


# ─── Main Processing Function ────────────────────────────────────────────────

async def process_with_harness(
    user_message: str,
    chat_id: int,
    context,
    send_response=None,
) -> bool:
    """
    Process a message through the Harness Agent (Claude CLI with orchestrator prompt).

    This is the PRIMARY processing mode. Claude CLI controls the computer
    and coordinates multiple AI tools as needed.

    Returns True if successful, False to fall back to API mode.
    """

    # Helper to send messages back to Telegram
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
                    logger.error(f"Failed to send message: {e}")

    try:
        # Build the full prompt with system instructions + quota context
        quota_ctx = _get_quota_context()
        full_prompt = f"{user_message}{quota_ctx}"

        # Get or create session for conversation continuity
        session_id = _get_session_id(chat_id)
        claude_cmd = _get_claude_cmd()

        # Build the CLI command
        cmd = [claude_cmd, "-p"]

        # Resume existing session for long conversations
        if session_id:
            cmd.extend(["--resume", session_id])

        # Add system prompt on first message (no session yet)
        if not session_id:
            cmd.extend(["--system-prompt", HARNESS_SYSTEM_PROMPT])

        # Add the user's message
        cmd.append(full_prompt)

        await _send("🤖 Harness Agent 处理中...")
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass

        # Execute Claude CLI
        # Run in a thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _run_claude_cli(cmd, timeout=300),
        )

        if result["success"]:
            # Try to capture session ID from output for continuation
            new_session_id = result.get("session_id")
            if new_session_id:
                _save_session_id(chat_id, new_session_id)
            elif not session_id:
                # Claude CLI might output session info — try to parse it
                parsed_id = _parse_session_id(result["output"])
                if parsed_id:
                    _save_session_id(chat_id, parsed_id)

            # Record quota usage if we can detect which platform was used
            quota = _get_quota()
            if quota:
                quota.record("claude_cli")

            # Send response
            await _send(result["output"])
            return True
        else:
            error = result.get("error", "Unknown error")
            logger.error(f"Claude CLI failed: {error}")

            if "rate limit" in error.lower() or "token" in error.lower():
                await _send(
                    "⏳ Claude CLI 达到用量限制。\n"
                    "可以等待恢复，或直接在 Telegram 中用 API 模式回复。"
                )
                quota = _get_quota()
                if quota:
                    quota.record("claude_cli", rate_limited=True)
            else:
                await _send(f"⚠️ Harness Agent 错误: {error[:500]}")

            return False

    except Exception as e:
        logger.error(f"Harness mode error: {e}", exc_info=True)
        await _send(f"⚠️ Harness 出错: {str(e)[:300]}")
        return False


def _run_claude_cli(cmd: list[str], timeout: int = 300) -> dict:
    """
    Run Claude CLI and capture output.

    Returns:
        {"success": bool, "output": str, "error": str, "session_id": str}
    """
    try:
        env = os.environ.copy()
        # Ensure Claude CLI can find its config
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            return {
                "success": True,
                "output": output or "(no output)",
                "error": "",
                "session_id": _parse_session_id(output) or _parse_session_id(result.stderr),
            }
        else:
            return {
                "success": False,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() or f"Exit code {result.returncode}",
                "session_id": "",
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": "",
            "error": f"Claude CLI timed out after {timeout}s. Task may still be running.",
            "session_id": "",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "output": "",
            "error": "Claude CLI not found. Install: npm install -g @anthropic-ai/claude-code",
            "session_id": "",
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e),
            "session_id": "",
        }


def _parse_session_id(text: str) -> str | None:
    """Try to extract a session ID from Claude CLI output."""
    if not text:
        return None
    import re
    # Claude CLI outputs session ID in various formats
    patterns = [
        r"session[_\s]?id[:\s]+([a-f0-9-]+)",
        r"--resume\s+([a-f0-9-]+)",
        r"Session:\s+([a-f0-9-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


# ─── Session Management ──────────────────────────────────────────────────────

def clear_session(chat_id: int):
    """Clear the harness session for a chat (start fresh)."""
    sessions = _load_sessions()
    sessions.pop(str(chat_id), None)
    _save_sessions(sessions)


def get_session_info(chat_id: int) -> str:
    """Get session info for a chat."""
    sessions = _load_sessions()
    info = sessions.get(str(chat_id))
    if not info:
        return "No active Harness session."
    updated = time.strftime("%Y-%m-%d %H:%M", time.localtime(info.get("updated_at", 0)))
    return (
        f"Session: {info.get('session_id', 'unknown')}\n"
        f"Last active: {updated}"
    )


# ─── Status & Commands ───────────────────────────────────────────────────────

def get_quota_status() -> str:
    """Get quota status for /quota command."""
    quota = _get_quota()
    if quota:
        return quota.status_report()
    return "Quota tracker not available."


def get_harness_status() -> str:
    """Get harness status for /status command."""
    lines = [
        "🤖 Harness Agent 状态",
        "─" * 30,
        "",
        "模式: Claude CLI 控制电脑 (PRIMARY)",
        "",
        "能力:",
        "  ✅ 直接回答问题",
        "  ✅ 写代码 (自身就是 Claude Code)",
        "  ✅ 打开多个 AI 窗口并行工作",
        "  ✅ 用鼠标键盘操控所有 AI 工具",
        "  ✅ 截图监控各窗口进度",
        "  ✅ 打开 Gemini 生成图片",
        "  ✅ Git 合并多 agent 结果",
        "  ✅ 自适应 — 平台满了自动切换",
        "",
        "架构:",
        "  TG → Claude CLI (有39个工具) → 控制电脑",
        "       ├─ 简单 → 直接回答",
        "       ├─ 代码 → 自己写 / 开 Claude Code",
        "       ├─ 复杂 → 多窗口并行",
        "       └─ 图片 → 开 Gemini",
    ]

    # Add Claude CLI status
    try:
        claude_cmd = _get_claude_cmd()
        result = subprocess.run(
            [claude_cmd, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            lines.append(f"\nClaude CLI: ✅ {result.stdout.strip()}")
        else:
            lines.append("\nClaude CLI: ⚠️ installed but error")
    except Exception:
        lines.append("\nClaude CLI: ❌ not found")

    # Add quota info
    quota = _get_quota()
    if quota:
        lines.append("")
        lines.append(quota.status_report())

    # Add active sessions
    sessions = _load_sessions()
    if sessions:
        lines.append(f"\n活跃对话: {len(sessions)} 个")

    return "\n".join(lines)
