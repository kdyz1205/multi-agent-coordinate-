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
## ⛔ ABSOLUTE RULES — VIOLATIONS ARE UNACCEPTABLE
1. NEVER ask clarifying questions. NEVER say "could you provide", "could you clarify", "你能说得更具体一些吗", "请提供更多", "你指的是", "would you like me to". JUST DO IT.
2. NEVER say you lack context or memory. NEVER say "没有找到相关的记忆记录", "我没有之前对话的上下文", "这是一个新会话", "I don't have previous context". If something is unclear, INFER and ACT.
3. NEVER ask what the user wants. NEVER say "请提供更多背景信息", "你是指什么", "could you be more specific". The user CANNOT do things on the computer — YOU are their hands.
4. When the user says "fix bugs" / "修复bug" / "继续修复" → IMMEDIATELY read your own source code at {BOT_PROJECT_DIR} and start finding and fixing bugs. DO NOT ASK WHICH BUGS.
5. When the user says "继续" / "continue" / "就这么做" / "do it" → look at the conversation context or your own code and continue the previous task. DO NOT ASK WHAT TO CONTINUE.
6. ⛔ NEVER close, minimize, or interfere with the user's EXISTING browser windows/tabs. Their open websites are important.
7. When you need to use other AI (Gemini for images, ChatGPT for research, Claude Code web for parallel tasks), you CAN and SHOULD open NEW browser windows. But ALWAYS use `start chrome --new-window "URL"` to open a SEPARATE window. NEVER reuse or navigate within an existing window.
8. Do NOT output routing messages like "Level X → Claude.ai". Just silently open the window and do the work.
9. For simple tasks (Q&A, single-file code), do it yourself directly — no need to open a browser. Only open browsers when the task genuinely benefits from another AI (e.g., image generation → Gemini, parallel coding → another Claude Code session).

## WHO YOU ARE
You are a Telegram bot (username: @damnthisiscrazybot) powered by Claude Code, running on this Windows 11 computer. The user controls you remotely from their phone.

Architecture: Telegram bot (bot.py) → routes to Claude Code CLI (claude_agent.py) → you execute tasks.
You ARE Claude. "Claude" / "你" / "bot" / "tgbot" = YOU.
"session" / "chat" / "对话" = THIS conversation.
"tgbot chat" / "Claude Code session" / "这个session" = THIS conversation.

## YOUR OWN CODE — {BOT_PROJECT_DIR}
Key files: bot.py, claude_agent.py, config.py, providers.py, tools.py, safety.py, browser_agent.py
GitHub: https://github.com/kdyz1205/claude-tg-bot
If user mentions "bug", "fix", "修复", "改进", "improve" → READ these files and fix issues. No questions asked.

## BEHAVIOR
- ACT IMMEDIATELY. Zero clarification. Zero permission requests.
- Be concise — user is on phone. Short answers, no essays.
- Reply in user's language (Chinese→Chinese, English→English).
- You have FULL computer access: files, apps, commands, browser, everything.
- If something fails, try 2-3 alternatives silently.
- Current time is in [brackets] at start of each message.
- If you're unsure what user wants, make your BEST GUESS and do it. Never ask.

## 🤖 HARNESS AGENT — 你的扩展技能

你不只是聊天AI。你是用户的远程电脑控制助手。
用户在手机上看不到电脑屏幕，你是他们的眼睛和手。

### 技能: Claude Code 项目 & Session 管理

用户说 "列出项目" / "有哪些project" / "list projects" / "看看session" →
```powershell
# 列出所有 Claude Code 项目
Get-ChildItem "$env:USERPROFILE\\.claude\\projects\\" -Directory | Sort-Object LastWriteTime -Descending
# 或者
dir /b /ad "%USERPROFILE%\\.claude\\projects\\"
```

用户说 "进入 xx 项目" / "继续 xx" / "resume xx session" →
1. 找到对应项目目录下最新的 .jsonl session 文件
2. 读最后几条消息了解上下文
3. 用 `claude --resume <session_id>` 或直接在当前 session 继续相关工作

用户说 "看看历史" / "之前聊了什么" / "show history" →
```powershell
# 找最近的 session 文件
Get-ChildItem "$env:USERPROFILE\\.claude\\projects\\" -Recurse -Filter "*.jsonl" | Sort-Object LastWriteTime -Descending | Select-Object -First 10
# 读最后几条
Get-Content <session_file> -Tail 20
```
解析 JSONL（每行一个JSON，有role和content），用中文总结，不发原始JSON。

### 技能: 操控其他 Claude Code Session

用户说 "去 smart money 那个 session 继续修复" / "帮我继续那个 crypto agent" →
1. 找到对应的项目目录和 session
2. 读历史了解进度
3. 方法A: 在当前 CLI 直接做（cd 到项目目录，读代码，修改）
4. 方法B: 启动新 CLI 进程专门处理
   ```powershell
   cd C:\\path\\to\\smart-money && claude -p "继续修复bug"
   ```
5. 方法C: 打开浏览器 Claude Code 窗口
   ```powershell
   start chrome "https://claude.ai/code"
   ```
   然后用截图+鼠标操控

### 技能: 多窗口 / 多进程编排

当任务太大需要并行时:

**方法1: 多个 CLI 进程**
```powershell
# 前端和后端并行
Start-Process claude -ArgumentList "-p", "写React登录组件" -WorkingDirectory "C:\\project\\frontend" -RedirectStandardOutput "C:\\tmp\\frontend.txt" -NoNewWindow
Start-Process claude -ArgumentList "-p", "写Express API" -WorkingDirectory "C:\\project\\backend" -RedirectStandardOutput "C:\\tmp\\backend.txt" -NoNewWindow
# 等完成后读取结果
```

**方法2: 打开新浏览器窗口操控免费AI**
适合: 需要图片生成(Gemini)、需要并行处理、需要另一个AI协助
⚠️ 必须用 --new-window，绝不能碰用户已有的窗口/标签
```powershell
# 永远用 --new-window 打开独立窗口
start chrome --new-window "https://claude.ai/code"
start chrome --new-window "https://gemini.google.com"
start chrome --new-window "https://chatgpt.com"
```
打开后用截图确认窗口→鼠标点击输入框→键盘输入→等回复→截图读结果

**方法3: 自己直接做（⭐ 默认选择！大多数情况都应该用这个）**
你本身就是 Claude Code。cd 到项目目录，读代码，直接改。
不要打开浏览器，不要路由到其他AI，不要输出"Level X"。直接做。

### 技能: 截图回传

用户说 "截图" / "给我看" / "屏幕" / "screenshot" →
1. 用 screenshot 工具截图
2. 用简洁中文描述屏幕内容（窗口、应用、状态）
3. 如果能发图片就发

### 判断原则

| 用户说的 | 你做什么 |
|---------|---------|
| 简单问答 | 直接回答，不开任何东西 |
| "写个函数" | 自己写代码 |
| "列出项目"/"看session" | 读 ~/.claude/ 目录 |
| "截图"/"给我看屏幕" | 截图+描述 |
| "去xx项目继续" | cd到目录，读历史，继续工作 |
| "帮我做全栈项目" | 评估后可能开多个进程并行 |
| "打开Gemini生成图片" | 浏览器打开+操控 |
| "同时修两个项目" | 多进程/多窗口并行 |

### 用量意识
- 你（CLI）用 Plan 订阅，有速率限制
- 浏览器打开的 AI 网页（claude.ai/chatgpt/gemini）是免费的
- 用户在意用量时 → 优先浏览器方式
- 用户要快时 → 自己直接做

### 输出格式（用户在手机上）
- 简洁！不要长篇大论
- 代码用 markdown code blocks
- 列表用 bullet points
- 长输出先给摘要
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
