# Agent Harness Skill

Use this skill when the user wants to:
- Create a multi-agent harness from natural language
- Set up agent collaboration (coder + reviewer, pipeline, etc.)
- Configure cross-session communication
- Run agent loops

## How to use

When the user describes what agents they want and how they should collaborate,
use this skill to generate a working harness configuration.

### Step 1: Parse the user's intent

Extract from their description:
- **Agents**: What roles? (coder, reviewer, integrator, planner, tester)
- **Loop mode**: self-loop, ping-pong, or pipeline?
- **Channel**: file (local), git (cross-session), or API (real-time)?
- **Convergence**: How many iterations? What quality threshold?

### Step 2: Generate the harness

```python
from harness import Harness

# Option A: From natural language
harness = Harness.from_natural_language("""
    <paste user's description here>
""")

# Option B: From YAML config
harness = Harness.from_config("config/my_harness.yaml")

# Export config for other sessions
print(harness.to_yaml())
```

### Step 3: Wire up handlers

Each agent needs a handler that defines what it actually does:

```python
from agents import create_coder_agent, create_reviewer_agent

coder = create_coder_agent(channel_type="git")
reviewer = create_reviewer_agent(channel_type="git")

# Custom handler example
@coder.on_receive
def my_coder(handoff):
    # Call your LLM, run your tool, etc.
    # Add files to handoff.files
    # Set handoff.convergence_score
    return handoff
```

### Step 4: Run the loop

```python
result = harness.run()
print(f"Converged: {result.converged} after {result.iterations} iterations")
```

## Cross-Session Collaboration

To hand off work between Claude Code sessions:

### Session A (producer):
```python
from harness import Harness
from harness.channels import GitChannel

channel = GitChannel(repo_dir=".", remote="origin")
handoff = coder.create_handoff(target="integrator", instructions="Merge into main site")
handoff.add_file("components/dashboard.js", code_content, language="javascript")
channel.send(handoff)
# Git push happens automatically
```

### Session B (consumer):
```python
from harness.channels import GitChannel

channel = GitChannel(repo_dir=".", remote="origin")
handoff = channel.receive("integrator")
# Now has all the files and instructions from Session A
```

## YAML Config Format

```yaml
name: my-project-harness
channel:
  type: git
  config:
    repo_dir: "."
    remote: origin
loop:
  mode: ping_pong
  max_iterations: 10
  convergence_threshold: 0.9
agents:
  - name: coder
    role: coder
    description: "Writes Python backend code"
    capabilities: [python, fastapi, postgresql]
    working_dir: ./src
  - name: reviewer
    role: reviewer
    description: "Reviews code for quality and security"
    capabilities: [code_review, security_audit]
    working_dir: ./src
```
