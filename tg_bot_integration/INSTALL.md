# Harness Agent — 增强你的 TG Bot

## 核心理解

**你的 bot 已经是一个 Harness Agent 了。** 它用 Claude CLI 控制电脑。

我们要做的不是"另建一个系统"，而是**增强它的 system prompt**，
教它新技能（多窗口编排、项目管理、截图回传等）。

```
现在你的 bot:
  TG → claude_agent.py → Claude CLI → 执行任务 → 回 TG
                              ↑
                        只有基础 system prompt
                        (知道自己是 TG bot，不问问题)

加了 Harness 后:
  TG → claude_agent.py → Claude CLI → 执行任务 → 回 TG
                              ↑
                        增强版 system prompt
                        + 列出项目
                        + 查看历史记录
                        + 多窗口编排
                        + 截图给用户看
                        + 智能判断是自己做还是开新窗口
```

## 安装 (2 步)

### Step 1: 复制文件

```
harness_prompt.py → claude-tg-bot/harness_prompt.py
```

### Step 2: 在 claude_agent.py 中引用

找到 `_SYSTEM_PROMPT = f"""` 那一行（大约在第 40 行），在末尾加上 Harness 增强：

```python
# 在文件顶部加 import
from harness_prompt import HARNESS_ENHANCEMENT

# 找到 _SYSTEM_PROMPT = f""" ... """
# 在 """ 结尾之前加一行:
_SYSTEM_PROMPT = f"""
{你现有的内容不动}

{HARNESS_ENHANCEMENT}
"""
```

就这么多。**不需要改 process_message，不需要改路由逻辑。**
因为你的 bot 已经在用 Claude CLI，我们只是教它新技能。

## 能做什么

装完后，你在 TG 上说：

| 你说的 | Bot 做的 |
|--------|---------|
| "列出项目" / "list projects" | 读 ~/.claude/projects/，返回项目列表 |
| "看看 xx 项目的历史" | 读 JSONL 文件，返回最近消息 |
| "截图" / "给我看屏幕" | 截图 + 描述屏幕内容 |
| "帮我做全栈项目" | 可能开多个 Claude Code 进程并行 |
| "打开 Gemini 生成 logo" | 用 shell 打开浏览器，操控 Gemini |
| "进入 xx 项目继续" | cd 到目录，读历史，继续工作 |
| "现在有哪些 session" | 列出活跃的 session |

## 关于截图

你的 bot 已经有 `screenshots.py`，Claude CLI 也有截图工具。
Harness prompt 教 Claude 在用户需要时主动截图并描述屏幕。

但注意：目前截图是**描述**给你看（文字形式），不是直接发图片。
因为 Claude CLI 的输出是文字。如果你需要直接发图片，
需要 Claude 截图保存文件 → bot 读取文件 → 发到 TG。
这个流程你的 bot 已经支持（通过 screenshot 命令）。

## 关于多窗口

Claude CLI 可以：
1. 用 `start chrome "url"` 打开多个浏览器窗口
2. 用 `claude -p "task" &` 启动多个 CLI 进程
3. 用 screenshot 监控各窗口进度
4. 用鼠标键盘在窗口间切换操作

但这些是**Claude 自己判断**要不要做的。
你只需要给它任务，它自己决定用什么方式。

## FAQ

**Q: 为什么不用 Playwright 脚本？**
A: Claude CLI 自己就能控制浏览器。它能看屏幕（截图）、判断点哪里（AI推理）、点击操作。
   比死板的 CSS selector 脚本灵活得多。UI 变了也能适应。

**Q: 会不会两次调用？**
A: 不会。Harness 不是新的处理路径，是**增强现有的 system prompt**。
   消息只走一条路：TG → Claude CLI → 回 TG。

**Q: 能看到 Claude Code 网页上的项目吗？**
A: 能看到本地 CLI 的项目（~/.claude/projects/）。
   网页上的项目需要 Claude 打开浏览器 claude.ai → 截图给你看。

**Q: 多窗口编排会用额外的 token 吗？**
A: 如果 Claude CLI 开新的 CLI 进程（`claude -p "task"`），那每个进程会用 Plan token。
   如果它开浏览器窗口操控免费的 AI 网页，那是免费的。
   Claude 会根据 system prompt 里的指引来判断用哪种方式。
