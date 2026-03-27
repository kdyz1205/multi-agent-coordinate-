# Multi-Agent Coordinate

A framework for agent self-loop iteration and cross-session collaboration.

## Architecture

```
                    ┌─────────────────────────────┐
                    │         Harness Core         │
                    │   (Orchestrator + NL Parser)  │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
       ┌──────▼──────┐  ┌─────▼──────┐  ┌──────▼──────┐
       │  Self-Loop   │  │  Ping-Pong │  │  Pipeline   │
       │  (1 agent)   │  │ (2 agents) │  │ (N agents)  │
       └──────┬──────┘  └─────┬──────┘  └──────┬──────┘
              │                │                │
              └────────────────┼────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
       ┌──────▼──────┐  ┌─────▼──────┐  ┌──────▼──────┐
       │    File      │  │    Git     │  │    API      │
       │   Channel    │  │  Channel   │  │  Channel    │
       │  (local)     │  │  (cross-   │  │  (real-     │
       │              │  │  session)  │  │   time)     │
       └─────────────┘  └────────────┘  └─────────────┘
```

## Quick Start

### 1. From Natural Language

```python
from harness import Harness

harness = Harness.from_natural_language("""
    Create a coder and reviewer agent.
    They alternate in a ping-pong loop.
    Loop 8 times or until score above 0.9.
""")

# Wire up handlers
for name, agent in harness.agents.items():
    @agent.on_receive
    def handle(handoff, n=name):
        handoff.convergence_score += 0.15
        return handoff

result = harness.run()
```

### 2. From YAML Config

```python
harness = Harness.from_config("config/default_harness.yaml")
```

### 3. Cross-Session Collaboration

**Session A** (generates code):
```python
from harness.channels import GitChannel
from harness.protocol import Handoff

handoff = Handoff(source_agent="coder", target_agent="integrator")
handoff.add_file("components/Dashboard.jsx", code, language="javascript")

channel = GitChannel(repo_dir=".", remote="origin")
channel.send(handoff)  # Commits and pushes via git
```

**Session B** (integrates):
```python
channel = GitChannel(repo_dir=".", remote="origin")
handoff = channel.receive("integrator")
# Now has all files and instructions from Session A
```

## Communication Channels

| Channel | Use Case | Speed | Cross-Machine |
|---------|----------|-------|---------------|
| File    | Same machine, local dev | Fastest | No |
| Git     | Cross-session, versioned | Medium | Yes |
| API     | Real-time, remote agents | Variable | Yes |

## Loop Modes

- **Self-loop**: One agent iterates on its own output (refining, improving)
- **Ping-pong**: Two agents alternate (coder writes, reviewer critiques)
- **Pipeline**: Chain of agents (planner -> coder -> reviewer -> tester -> integrator)

## Project Structure

```
harness/
├── core.py           # Main orchestrator, NL parser
├── protocol.py       # Handoff schema, message format
├── agent.py          # Agent definition, lifecycle
├── loop.py           # Loop controller (self, ping-pong, pipeline)
├── channels/
│   ├── file_channel.py   # Local filesystem
│   ├── git_channel.py    # Git branches
│   └── api_channel.py    # HTTP API
└── templates/
    └── claude_code_harness.yaml

agents/                # Pre-built agent templates
├── coder.py
├── reviewer.py
└── integrator.py

config/                # YAML configs
├── default_harness.yaml
└── cross_session_harness.yaml

examples/              # Runnable demos
├── self_loop_demo.py
├── cross_session_demo.py
└── natural_language_demo.py
```

## License

MIT
