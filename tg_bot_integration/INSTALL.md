# Harness Agent — 让你的 TG Bot 变成 AI 总管

## 这是什么？

**Harness Agent** = Claude CLI (有39个工具) + 编排指令 = **一个有眼睛和手的AI总管**

它通过 Telegram 接收你的指令，然后**控制你的电脑**来完成任务：
- 简单问题 → 直接回答
- 写代码 → 自己写（它本身就是 Claude Code）
- 复杂任务 → 打开多个 AI 窗口，分配任务，监控进度
- 生成图片 → 打开 Gemini，操控生成
- 选择方案 → 用鼠标在 Claude Code 里选 plan

```
你手机 (Telegram)
  │
  │ "帮我做一个全栈项目"
  │
  ▼
TG Bot → Claude CLI (Harness Agent)
           │  它有: 截图、鼠标、键盘、Shell、文件、浏览器
           │
           ├─ 打开 Claude Code 窗口1 → 前端任务
           ├─ 打开 Claude Code 窗口2 → 后端任务
           ├─ 打开 Gemini → 生成 logo
           ├─ 监控进度（截图查看）
           ├─ 在 Claude Code 里选择 plan → 点 approve
           └─ 全部完成 → git merge → 回报给你

成本: Plan 订阅 (免费额度内)
```

## 对比

| | 之前 (Playwright 脚本) | 现在 (Harness Agent) |
|---|---|---|
| 方式 | 死板的 CSS selector 粘贴文字 | AI 看屏幕，智能决定下一步 |
| 能力 | 只能文字输入→输出 | 鼠标、键盘、截图、选plan、生成图片 |
| 适应性 | UI 一改就挂 | AI 自己判断点哪里 |
| 多窗口 | 脚本并行但不智能 | AI 监控各窗口进度，智能调度 |
| Session | 每次都新开 | 长对话，记住上下文 |

## 安装 (4 步)

### Step 1: 复制文件

把这 3 个文件放到你的 `claude-tg-bot/` 目录：

```
harness_mode.py     → claude-tg-bot/harness_mode.py
web_ai.py           → claude-tg-bot/web_ai.py      (fallback, 可选)
quota_tracker.py    → claude-tg-bot/quota_tracker.py
```

### Step 2: config.py 加一行

```python
# Harness Agent — PRIMARY mode
HARNESS_MODE = os.getenv("HARNESS_MODE", "true").lower() == "true"
```

### Step 3: 改 claude_agent.py — Harness 为主

找到 `process_message` 函数，改成 Harness 优先：

```python
async def process_message(user_message: str, chat_id: int, context):
    lock = _get_lock(chat_id)

    if lock.locked():
        _queue_message(chat_id, user_message)
        queue_size = len(_pending_messages.get(chat_id, []))
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📝 收到 (第{queue_size}条追加)。",
            )
        except Exception:
            pass
        return

    async with lock:
        # ★ PRIMARY: Harness Agent (Claude CLI + 电脑控制 + 编排)
        if getattr(config, "HARNESS_MODE", True):
            try:
                from harness_mode import process_with_harness
                success = await process_with_harness(
                    user_message, chat_id, context,
                    send_response=_send_response,
                )
                if success:
                    return
                logger.warning("Harness Agent failed, falling back")
            except ImportError:
                logger.warning("harness_mode.py not found")
            except Exception as e:
                logger.error(f"Harness error: {e}", exc_info=True)

        # FALLBACK 1: Plain Bridge mode (no harness system prompt)
        if getattr(config, "BRIDGE_MODE", True):
            success = await _process_with_claude_cli(user_message, chat_id, context)
            if success:
                return

        # FALLBACK 2: API mode (costs money)
        try:
            from providers import process_with_auto_fallback
            # ... existing API fallback code ...
```

**关键区别**: Harness Agent 和普通 Bridge Mode 都用 Claude CLI，
但 Harness Agent 多了一个 system prompt 教它如何编排多窗口。

### Step 4: 加 bot 命令

在 `bot.py` 的 `main()` 里加：

```python
app.add_handler(CommandHandler("harness", harness_command, filters=auth_filter))
app.add_handler(CommandHandler("quota", quota_command, filters=auth_filter))
app.add_handler(CommandHandler("hclear", harness_clear_command, filters=auth_filter))
```

函数：

```python
async def harness_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        try:
            from harness_mode import get_harness_status
            await update.message.reply_text(get_harness_status())
        except ImportError:
            await update.message.reply_text("harness_mode.py 未安装")
        return
    action = context.args[0].lower()
    if action == "on":
        config.HARNESS_MODE = True
        await update.message.reply_text("✅ Harness Agent ON")
    elif action == "off":
        config.HARNESS_MODE = False
        await update.message.reply_text("✅ Harness Agent OFF (fallback to Bridge)")


async def quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from harness_mode import get_quota_status
        await update.message.reply_text(get_quota_status())
    except ImportError:
        await update.message.reply_text("未安装")


async def harness_clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear harness session (start fresh conversation)."""
    try:
        from harness_mode import clear_session
        clear_session(update.effective_chat.id)
        await update.message.reply_text("✅ Harness session cleared. 下次消息会开始新对话。")
    except ImportError:
        await update.message.reply_text("未安装")
```

### .env

```env
HARNESS_MODE=true
BRIDGE_MODE=true
```

## 使用

安装后，你的 bot 自动用 Harness Agent 处理所有消息：

| 你发的消息 | Harness Agent 做什么 |
|-----------|---------------------|
| "什么是 React？" | 直接回答（不开浏览器） |
| "帮我写一个函数" | 自己写代码返回 |
| "帮我做一个全栈项目" | 打开多个 Claude Code 窗口，分配前后端 |
| "帮我截个图" | 用截图工具截图 |
| "打开 Gemini 生成一个 logo" | 控制浏览器打开 Gemini，操控生成 |

## 命令

| 命令 | 说明 |
|------|------|
| `/harness` | 查看 Harness Agent 状态 |
| `/harness on/off` | 开关 |
| `/quota` | 查看各平台用量 |
| `/hclear` | 清除当前 harness 对话（重新开始） |

## Session 持久性

Harness Agent 会保持 Claude CLI session：
- 你发第一条消息 → 开始新 session
- 后续消息 → 继续同一 session（有上下文记忆）
- `/hclear` → 清除 session，下次重新开始

这意味着你可以在 TG 上进行**很长的对话**，Claude 会记住之前说了什么。

## 原理

1. **harness_mode.py** 调用 `claude -p --system-prompt "..." "你的消息"`
2. Claude CLI 收到消息 + Harness 编排指令
3. Claude 自己决定要不要开浏览器、开几个窗口、怎么分配任务
4. 所有操控都通过 Claude 的 computer use 工具（截图→分析→点击）
5. 完成后输出结果，harness_mode.py 发回 Telegram

**web_ai.py** 是简化版 fallback — 只在 Claude CLI 不可用时使用。
