"""
Multi-Agent Coordinate Harness Framework

Patterns incorporated from:
- CrewAI: Role+Goal+Backstory agents, Task context chaining, delegation
- LangGraph: Shared state, checkpointing, supervisor/swarm patterns
- Anthropic: Orchestrator-worker, evaluator-optimizer, prompt chaining

Supports file-based, git-based, and API-based communication channels.
"""

from harness.protocol import Handoff, Message, AgentRole
from harness.agent import Agent, AgentConfig
from harness.task import Task, TaskResult
from harness.loop import LoopController
from harness.evaluator import EvaluatorOptimizer, EvalFeedback
from harness.orchestrator import OrchestratorWorker
from harness.core import Harness
from harness.memory import ShortTermMemory, LongTermMemory, SharedState

__version__ = "0.2.0"
__all__ = [
    "Harness", "Agent", "AgentConfig",
    "Task", "TaskResult",
    "Handoff", "Message", "AgentRole",
    "LoopController",
    "EvaluatorOptimizer", "EvalFeedback",
    "OrchestratorWorker",
    "ShortTermMemory", "LongTermMemory", "SharedState",
]
