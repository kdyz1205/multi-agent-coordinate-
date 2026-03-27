# Multi-Agent Coordinate

A complete harness framework that lets you send a Telegram message, auto-dispatches to the best free AI web interface (GPT, Grok, Claude, Codex) via browser automation, and merges results through Git.

**Core principle: Don't burn API tokens. Use your existing AI subscriptions via browser automation. Zero marginal cost.**

## Full Pipeline

```
You (Telegram)
     │
     ▼
┌──────────────────────────────────────────┐
│  Telegram Bot (gateway/telegram_bot.py)   │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│  Dispatcher (dispatcher/)                 │
│                                           │
│  Classifies task difficulty:              │
│  Level 1 (Q&A)      → GPT/Grok    free  │
│  Level 2 (Code)     → Claude Web   free  │
│  Level 3 (Heavy)    → Claude Code  free  │
│  Level 4 (Multi)    → 2x Claude    free  │
│  Level 5 (Arch)     → Code + Codex free  │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│  Browser Agents (browser_agents/)         │
│  Playwright automates your browser:       │
│                                           │
│  ┌─────────┐ ┌─────────┐ ┌────────────┐ │
│  │  GPT    │ │  Grok   │ │ Claude Web │ │
│  │  Tab    │ │  Tab    │ │    Tab     │ │
│  └────┬────┘ └────┬────┘ └─────┬──────┘ │
│       │           │            │         │
│       ▼           ▼            ▼         │
│  Find input → Paste prompt → Wait → Extract code
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│  Git Merger (pipeline/git_merger.py)      │
│                                           │
│  Agent A code → branch A ─┐              │
│  Agent B code → branch B ─┼─→ merge → main
│  Agent C code → branch C ─┘              │
└──────────────────┬───────────────────────┘
                   │
                   ▼
              Result → Telegram
```

## Quick Start

### 1. Install

```bash
pip install -e .
playwright install chromium
```

### 2. Run the Telegram Bot

```bash
export TELEGRAM_BOT_TOKEN=your_token_from_botfather
export CHROME_USER_DATA=/path/to/your/chrome/profile
python main.py
```

### 3. Send a task via Telegram

```
You: 帮我写一个 React 登录页面
Bot: Analyzing task...
     Difficulty: Level 2 (MODERATE)
     Platform: claude_web
     Executing...
Bot: [returns the generated code]
```

### 4. Or use directly in Python

```python
import asyncio
from pipeline import Orchestrator

orch = Orchestrator(repo_dir="/path/to/project")
result = asyncio.run(orch.execute("帮我写一个 React 登录页面"))
print(result.summary)
```

## Architecture Layers

### Layer 1: Gateway (Telegram Bot)
Your entry point. Send messages → harness receives them.

### Layer 2: Dispatcher (Rule-Based Router)
Classifies task difficulty using keyword matching. No API call needed — zero cost.
Upgradeable to local LLM (Ollama) for smarter dispatch.

### Layer 3: Browser Agents (Playwright)
The hands of the system. Opens your browser, navigates to AI platforms,
pastes prompts, waits for responses, extracts code. Uses YOUR login sessions.

| Platform | File | What it automates |
|----------|------|-------------------|
| ChatGPT | `browser_agents/chatgpt.py` | chatgpt.com |
| Grok | `browser_agents/grok.py` | grok.com |
| Claude Web | `browser_agents/claude_web.py` | claude.ai |
| Claude Code | `browser_agents/claude_code_web.py` | claude.ai/code |

### Layer 4: Git Merger
Merges output from multiple agents into a single branch.

### Layer 5: Harness Framework (Advanced)
For programmatic agent loops and cross-session coordination.

## Harness Framework (Agent Loops)

Beyond the Telegram pipeline, the harness supports programmatic agent orchestration:

```python
from harness import Harness

# Create from natural language
harness = Harness.from_natural_language("""
    Create a coder and reviewer agent.
    They alternate in a ping-pong loop.
    Loop 8 times or until score above 0.9.
""")

# Or from YAML
harness = Harness.from_config("config/default_harness.yaml")
```

### Loop Modes

- **Self-loop**: One agent iterates on its own output
- **Ping-pong**: Two agents alternate (coder + reviewer)
- **Pipeline**: Chain of agents (planner → coder → reviewer → tester)

### Communication Channels

| Channel | Use Case | Cost |
|---------|----------|------|
| File | Same machine | Free |
| Git | Cross-session | Free |
| API | Real-time remote | Free |

## Project Structure

```
main.py                    # Entry point: Telegram bot + full pipeline

gateway/
└── telegram_bot.py        # Telegram bot (your mouth)

dispatcher/
└── __init__.py            # Task classifier + router (your brain)

browser_agents/            # Browser automation (your hands)
├── base.py                # Abstract base class
├── chatgpt.py             # ChatGPT controller
├── grok.py                # Grok controller
├── claude_web.py          # Claude Web controller
└── claude_code_web.py     # Claude Code controller

pipeline/
├── orchestrator.py        # Full pipeline orchestrator
└── git_merger.py          # Multi-branch git merger

harness/                   # Advanced: agent loop framework
├── core.py                # Harness engine + NL parser
├── protocol.py            # Handoff schema
├── agent.py               # Agent definition
├── loop.py                # Loop controller
├── channels/              # Communication channels
│   ├── file_channel.py
│   ├── git_channel.py
│   └── api_channel.py
└── templates/

agents/                    # Pre-built agent templates
├── coder.py
├── reviewer.py
└── integrator.py

config/                    # YAML configs
├── default_harness.yaml
└── cross_session_harness.yaml

examples/
├── quick_start.py         # Test dispatcher + browser agents
├── self_loop_demo.py
├── cross_session_demo.py
└── natural_language_demo.py
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather | required |
| `CHROME_USER_DATA` | Chrome profile directory (reuse login sessions) | "" |
| `REPO_DIR` | Git repo directory for merging | "." |
| `GIT_REMOTE` | Git remote name | "origin" |
| `HEADLESS` | Run browser without UI | "false" |
| `TIMEOUT_MS` | Max wait for AI response | "120000" |

## License

MIT
