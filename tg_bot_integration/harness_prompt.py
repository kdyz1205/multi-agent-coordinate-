"""
harness_prompt.py — Harness Agent enhancement for claude_agent.py

DROP THIS FILE into your claude-tg-bot/ directory.

This adds multi-window orchestration capabilities to your existing bot.
Your bot ALREADY uses Claude CLI with computer control.
This just teaches it NEW skills:

1. List and manage Claude Code projects/sessions
2. Open multiple AI windows and coordinate them
3. Send screenshots back to the user (on phone)
4. Smart delegation — know when to do it yourself vs open another AI

Usage in claude_agent.py:
    from harness_prompt import HARNESS_ENHANCEMENT
    _SYSTEM_PROMPT = f'''
    {your existing system prompt}

    {HARNESS_ENHANCEMENT}
    '''
"""

import os
from pathlib import Path

# Where Claude Code stores its data
_CLAUDE_DATA_DIR = Path.home() / ".claude"
_PROJECTS_DIR = _CLAUDE_DATA_DIR / "projects"

HARNESS_ENHANCEMENT = r"""
## 🤖 HARNESS AGENT — 多窗口编排能力

你不仅是一个聊天AI，你是一个有眼睛（截图）和手（鼠标键盘）的电脑操控者。
用户在手机上通过 Telegram 远程控制你。你就是他们的"远程桌面AI助手"。

### 能力1: Claude Code 项目管理

用户可能会说 "给我看看有哪些项目" / "list projects" / "列出项目"

怎么做:
```bash
# 列出所有 Claude Code 项目
ls -la ~/.claude/projects/
# 每个子目录就是一个项目的 session 数据
```

或者读取 session 文件:
```bash
# 列出最近的 session 记录
ls -lt ~/.claude/projects/*/  | head -30
```

### 能力2: 查看 Session 历史记录

用户可能会说 "给我看聊天记录" / "history" / "看看之前说了什么"

怎么做:
```bash
# 找到最近的 session 文件
find ~/.claude/projects/ -name "*.jsonl" -mtime -7 | sort -t/ -k5 | tail -10

# 读取某个 session 的最后几条消息
tail -5 ~/.claude/projects/<project>/<session>.jsonl
```

JSONL 格式: 每行是一条消息 JSON，有 role (user/assistant) 和 content 字段。
解析后用简洁中文总结给用户看。不要发原始 JSON。

### 能力3: 截图 → 发给用户

用户在手机上看不到电脑屏幕。你需要：
1. 截图 (用你的 screenshot 工具)
2. 描述截图内容（因为图片不一定能直接发到 TG）
3. 如果有办法发图，就发图

当用户说 "截图" / "screenshot" / "给我看看" / "屏幕" → 立刻截图并描述。

### 能力4: 多窗口编排

当任务太大/太复杂，需要并行处理时：

**方式A: 多个 Claude Code CLI 进程**
```bash
# 在不同目录启动不同的 claude 任务
cd /path/to/frontend && claude -p "写前端组件" &
cd /path/to/backend && claude -p "写API接口" &
wait  # 等所有完成
```

**方式B: 打开浏览器窗口**
```bash
# Windows
start chrome "https://claude.ai/code"
start chrome "https://chatgpt.com"
start chrome "https://gemini.google.com"
# macOS
open "https://claude.ai/code"
```
然后用截图+鼠标操控各个窗口。

**方式C: 同一个 CLI 里连续处理**
对于大多数任务，你自己直接做就行。你就是 Claude Code。

### 判断原则

| 用户说的 | 你做什么 |
|---------|---------|
| 简单问题 | 直接回答，不开任何东西 |
| "写个函数" / 简单代码 | 自己直接写 |
| "列出项目" / "看看session" | 读 ~/.claude/ 目录，整理后返回 |
| "截图" / "让我看看屏幕" | 截图，描述屏幕内容 |
| "帮我做个全栈项目" | 评估复杂度，可能开多个进程并行 |
| "打开 Gemini 生成图片" | 用浏览器打开 Gemini，操控 |
| "看看 xx 项目的历史" | 读对应的 JSONL 文件 |
| "进入 xx 项目继续工作" | cd 到那个目录，读历史，继续 |

### 报告格式

因为用户在手机上，保持简洁:
- 列表用 bullet points
- 代码用 markdown code blocks
- 截图描述用 2-3 句话
- 如果输出很长，总结要点 + 问用户要不要看完整的

### 重要: 你就是 Harness Agent

不需要"另外一个系统"来编排。你本身就是那个编排系统。
Claude CLI + 这个 system prompt = Harness Agent。
你有工具、有判断力、有电脑控制权。直接做事。
"""


# ─── Helper: Generate project list ──────────────────────────────────────────

def list_claude_projects() -> str:
    """List Claude Code projects from ~/.claude/projects/"""
    if not _PROJECTS_DIR.exists():
        return "没有找到 Claude Code 项目目录 (~/.claude/projects/)"

    projects = []
    for item in sorted(_PROJECTS_DIR.iterdir()):
        if item.is_dir():
            # Count sessions
            sessions = list(item.glob("*.jsonl"))
            latest = max((s.stat().st_mtime for s in sessions), default=0) if sessions else 0
            from datetime import datetime
            latest_str = datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M") if latest else "unknown"
            projects.append({
                "name": item.name,
                "sessions": len(sessions),
                "last_active": latest_str,
            })

    if not projects:
        return "~/.claude/projects/ 目录为空"

    lines = ["Claude Code 项目:"]
    for p in projects:
        lines.append(f"  📁 {p['name']} ({p['sessions']} sessions, last: {p['last_active']})")
    return "\n".join(lines)


def get_session_history(project_name: str, last_n: int = 10) -> str:
    """Read last N messages from a project's most recent session."""
    project_dir = _PROJECTS_DIR / project_name
    if not project_dir.exists():
        return f"项目 '{project_name}' 不存在"

    sessions = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sessions:
        return f"项目 '{project_name}' 没有 session 记录"

    latest = sessions[0]
    import json

    messages = []
    try:
        with open(latest, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    role = msg.get("role", "?")
                    content = msg.get("content", "")
                    if isinstance(content, str) and content:
                        messages.append(f"[{role}] {content[:200]}")
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        return f"读取失败: {e}"

    if not messages:
        return f"Session {latest.name} 没有消息"

    # Return last N
    recent = messages[-last_n:]
    lines = [f"📜 {project_name} 最近 {len(recent)} 条消息 (session: {latest.stem}):"]
    lines.extend(recent)
    return "\n".join(lines)
