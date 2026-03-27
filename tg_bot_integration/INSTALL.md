# Harness Integration for claude-tg-bot

## How It Works — The Full Picture

```
你手机 (Telegram)
  │
  │ "帮我写一个 React 登录页面"
  │
  ▼
TG Bot (你电脑上运行)
  │
  ├─ 第1选择: Bridge Mode (Claude CLI, Plan tokens)
  │     ↓ 如果 rate limited...
  │
  ├─ 第2选择: ★ Harness Mode (新增!) ★
  │     │
  │     ├─ Dispatcher: 判断难度 (Level 1-5)
  │     ├─ Quota Tracker: 查哪个平台还有余量
  │     ├─ Browser: 打开 Chrome → 导航到 Claude/GPT/Grok
  │     ├─ 自动找到输入框 → 粘贴 prompt → 等回复
  │     ├─ 提取文字/代码 → 发回 Telegram
  │     └─ 如果这个平台也满了 → 自动切下一个
  │     ↓ 如果所有平台都满了...
  │
  └─ 第3选择: API Mode (烧 API tokens, 最后手段)

成本: Bridge = Plan tokens(免费) → Harness = 浏览器(免费) → API = 付费
```

## Install (3 Steps)

### Step 1: Copy 3 files

Copy these files into your `claude-tg-bot/` directory:

```
harness_mode.py    → C:\Users\alexl\Desktop\claude tg bot\harness_mode.py
web_ai.py          → C:\Users\alexl\Desktop\claude tg bot\web_ai.py
quota_tracker.py   → C:\Users\alexl\Desktop\claude tg bot\quota_tracker.py
```

### Step 2: Add to config.py

Add this line to `config.py`:

```python
# After the BRIDGE_MODE line:
HARNESS_MODE = os.getenv("HARNESS_MODE", "true").lower() == "true"
```

### Step 3: Patch claude_agent.py

In `claude_agent.py`, find the `process_message` function (around line 441).
Replace the fallback section with:

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
        # 1st: Bridge mode (Claude CLI, Plan tokens)
        if getattr(config, "BRIDGE_MODE", True):
            success = await _process_with_claude_cli(user_message, chat_id, context)
            if success:
                return
            logger.warning("Claude CLI failed, trying Harness mode")

        # 2nd: Harness mode (browser automation, $0)
        if getattr(config, "HARNESS_MODE", True):
            try:
                from harness_mode import process_with_harness
                success = await process_with_harness(
                    user_message, chat_id, context,
                    send_response=_send_response,
                )
                if success:
                    return
                logger.warning("Harness mode failed, falling back to API")
            except ImportError:
                logger.warning("harness_mode.py not found, skipping")
            except Exception as e:
                logger.error(f"Harness error: {e}", exc_info=True)

        # 3rd: API fallback (costs money)
        try:
            from providers import process_with_auto_fallback
            # ... (existing API fallback code stays the same)
```

### Step 4: Add /harness and /quota commands to bot.py

Add these handlers in `bot.py`'s `main()` function:

```python
# After the existing command handlers:
app.add_handler(CommandHandler("harness", harness_command, filters=auth_filter))
app.add_handler(CommandHandler("quota", quota_command, filters=auth_filter))
```

And add these functions:

```python
async def harness_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        status = "✅ 开启" if getattr(config, 'HARNESS_MODE', False) else "❌ 关闭"
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
        await update.message.reply_text("✅ Harness Mode 开启 (浏览器自动化)")
    elif action == "off":
        config.HARNESS_MODE = False
        await update.message.reply_text("✅ Harness Mode 关闭")


async def quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from harness_mode import get_quota_status
        await update.message.reply_text(get_quota_status())
    except ImportError:
        await update.message.reply_text("Harness 未安装。")
```

### Step 5: Add to .env

```
HARNESS_MODE=true
CHROME_USER_DATA=C:\Users\alexl\AppData\Local\Google\Chrome\User Data
```

### Step 6: Install Playwright (if not already)

```
pip install playwright
playwright install chromium
```

## Usage

After setup, your bot automatically tries:
1. Bridge (Plan tokens) → if rate limited →
2. Harness (browser, free) → if all platforms exhausted →
3. API (paid)

Commands:
- `/harness` — Status & on/off toggle
- `/quota` — See usage per platform
- `/harness on` / `/harness off` — Toggle

## Important Notes

- You MUST be logged in to claude.ai, chatgpt.com, grok.com in Chrome
- CSS selectors in `web_ai.py` may break when platforms update their UI
- First run: test with `/harness on` then send a simple message
- If browser automation fails, bot automatically falls back to API
