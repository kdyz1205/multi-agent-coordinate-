# Harness Integration for claude-tg-bot

## Architecture — Harness-First (零成本优先)

```
你手机 (Telegram)
  │
  │ "帮我写一个 React 登录页面"
  │
  ▼
TG Bot (你电脑上运行)
  │
  ▼
★ Harness Mode (PRIMARY — 自动分发到免费网页AI) ★
  │
  ├─ 1. 检测: 需要操控电脑?
  │     ├─ YES → Claude CLI (唯一有鼠标/键盘/文件工具的)
  │     └─ NO  → 继续分析...
  │
  ├─ 2. 分类任务难度 (Level 1-5, 纯规则, 零成本)
  │
  ├─ 3. 路由到最佳平台:
  │     ├─ Level 1 (Q&A/聊天)     → Grok / GPT     (最快)
  │     ├─ Level 2 (单文件代码)    → Claude Web      (免费)
  │     ├─ Level 3 (重度代码)      → Claude Code Web (免费)
  │     └─ Level 4-5 (多文件/架构) → 多平台并行分发  (免费)
  │
  ├─ 4. 浏览器自动化:
  │     Chrome → 导航到AI网站 → 粘贴prompt → 等回复 → 提取结果
  │
  ├─ 5. Adaptive Quota (自适应用量):
  │     如果一个平台满了 → 自动切到下一个可用平台
  │     自动记录用量 → 命中限制时自动降低估计值
  │
  └─ 6. 最后手段: API Mode (所有平台都满了才用, 花钱)

成本: Harness = 免费 → CLI = Plan (免费) → API = 付费
```

## Install (5 Steps)

### Step 1: Copy 3 files

Copy these files into your `claude-tg-bot/` directory:

```
harness_mode.py    → your-bot-dir/harness_mode.py
web_ai.py          → your-bot-dir/web_ai.py
quota_tracker.py   → your-bot-dir/quota_tracker.py
```

### Step 2: Add to config.py

```python
# Harness Mode — PRIMARY processing mode (free, browser automation)
HARNESS_MODE = os.getenv("HARNESS_MODE", "true").lower() == "true"
```

### Step 3: Patch claude_agent.py — Harness-First Routing

In `claude_agent.py`, find the `process_message` function.
Replace the processing logic to make Harness PRIMARY:

```python
async def process_message(user_message: str, chat_id: int, context):
    lock = _get_lock(chat_id)

    if lock.locked():
        _queue_message(chat_id, user_message)
        queue_size = len(_pending_messages.get(chat_id, []))
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📝 收到 (第{queue_size}条追加)，处理完当前任务后会一起看。",
            )
        except Exception:
            pass
        return

    async with lock:
        # ★ PRIMARY: Harness mode (browser automation, $0)
        # Routes to free web AI. Only sends computer-control tasks to CLI.
        if getattr(config, "HARNESS_MODE", True):
            try:
                from harness_mode import process_with_harness

                # Pass CLI as fallback for computer-control tasks
                async def _cli_fallback(msg, cid, ctx):
                    return await _process_with_claude_cli(msg, cid, ctx)

                success = await process_with_harness(
                    user_message, chat_id, context,
                    send_response=_send_response,
                    cli_fallback=_cli_fallback if getattr(config, "BRIDGE_MODE", True) else None,
                )
                if success:
                    return
                logger.warning("Harness mode failed, falling back to API")
            except ImportError:
                logger.warning("harness_mode.py not found, trying CLI")
            except Exception as e:
                logger.error(f"Harness error: {e}", exc_info=True)

        # FALLBACK 1: Bridge mode (only if Harness unavailable)
        if getattr(config, "BRIDGE_MODE", True):
            success = await _process_with_claude_cli(user_message, chat_id, context)
            if success:
                return
            logger.warning("Claude CLI also failed, falling back to API")

        # FALLBACK 2: API mode (costs money, last resort)
        try:
            from providers import process_with_auto_fallback
            # ... (existing API fallback code stays the same)
```

### Step 4: Add commands to bot.py

Add these handlers in `bot.py`'s `main()` function:

```python
app.add_handler(CommandHandler("harness", harness_command, filters=auth_filter))
app.add_handler(CommandHandler("quota", quota_command, filters=auth_filter))
app.add_handler(CommandHandler("route", route_test_command, filters=auth_filter))
```

And add these functions:

```python
async def harness_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        status = "✅ PRIMARY" if getattr(config, 'HARNESS_MODE', False) else "❌ OFF"
        try:
            from harness_mode import get_harness_status
            detail = get_harness_status()
        except ImportError:
            detail = "(harness_mode.py 未安装)"
        await update.message.reply_text(
            f"🌐 Harness Mode: {status}\n\n{detail}\n\n"
            "用法: /harness on|off"
        )
        return
    action = context.args[0].lower()
    if action == "on":
        config.HARNESS_MODE = True
        await update.message.reply_text("✅ Harness Mode 开启 (浏览器自动化, PRIMARY)")
    elif action == "off":
        config.HARNESS_MODE = False
        await update.message.reply_text("✅ Harness Mode 关闭 (回退到 CLI/API)")


async def quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from harness_mode import get_quota_status
        await update.message.reply_text(get_quota_status())
    except ImportError:
        await update.message.reply_text("Harness 未安装。")


async def route_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test routing without executing — shows where a message would go."""
    if not context.args:
        await update.message.reply_text("用法: /route <your message>\n测试消息会被路由到哪个平台")
        return
    test_msg = " ".join(context.args)
    try:
        from harness_mode import test_routing
        await update.message.reply_text(test_routing(test_msg))
    except ImportError:
        await update.message.reply_text("harness_mode.py 未安装")
```

### Step 5: Set .env

```env
# Harness Mode (PRIMARY)
HARNESS_MODE=true

# Chrome profile for persistent login sessions
# Windows:
CHROME_USER_DATA=C:\Users\<your-username>\AppData\Local\Google\Chrome\User Data
# macOS:
# CHROME_USER_DATA=~/Library/Application Support/Google/Chrome
# Linux:
# CHROME_USER_DATA=~/.config/google-chrome

# Bridge Mode (only for computer control tasks)
BRIDGE_MODE=true
```

### Prerequisites

```bash
pip install playwright
playwright install chromium
```

## First-Time Setup

1. **Login to AI platforms**: Open Chrome and log in to:
   - https://claude.ai (Claude Web + Claude Code)
   - https://chatgpt.com (ChatGPT)
   - https://grok.com (Grok)

   You only need to do this ONCE. The harness reuses your Chrome sessions.

2. **Test routing**: Send `/route 帮我写一个函数` to your bot to see where it would route.

3. **Test execution**: Send a simple message to your bot and watch Chrome open automatically.

## Commands

| Command | Description |
|---------|-------------|
| `/harness` | Show harness status & routing logic |
| `/harness on/off` | Toggle harness mode |
| `/quota` | Show per-platform usage & remaining quota |
| `/route <msg>` | Test routing without executing |

## Routing Logic

```
消息进来 → needs_computer_control() 检测
  │
  ├─ 需要操控电脑? (截图/打开文件/鼠标键盘...)
  │   └─ YES → Claude CLI (Bridge Mode)
  │
  └─ NO → classify_and_route() 分类
      │
      ├─ Level 1 (Q&A)     → Grok / GPT       (免费, 最快)
      ├─ Level 2 (单文件)   → Claude Web        (免费)
      ├─ Level 3 (重度代码)  → Claude Code Web   (免费)
      ├─ Level 4 (多文件)   → 多平台并行         (免费)
      └─ Level 5 (架构)     → 多平台并行         (免费)
          │
          └─ 如果目标平台满了 → Quota Tracker 自动切到下一个可用平台
              │
              └─ 所有平台都满了 → API Mode (付费, 最后手段)
```

## How Parallel Dispatch Works (Level 4-5)

For complex tasks, the harness automatically:
1. Splits the task into subtasks (by numbered items, "and" separators, or frontend/backend)
2. Assigns each subtask to a different AI platform
3. Executes ALL subtasks simultaneously (asyncio.gather)
4. Merges results and sends back to Telegram

Example:
```
User: "帮我写一个 React 前端 以及 Node.js 后端 API"

Harness:
  → Frontend → Claude Code Web (parallel)
  → Backend  → Claude Web (parallel)
  → Results merged → sent to Telegram
```

## Troubleshooting

- **"未登录"错误**: 在 Chrome 中手动登录该平台，然后重试
- **CSS selectors 失效**: AI 平台更新了 UI，需要更新 `web_ai.py` 中的 selectors
- **所有平台都满了**: 等 cooldown 结束，或用 `/quota` 查看何时恢复
- **浏览器没打开**: 检查 `CHROME_USER_DATA` 路径是否正确
