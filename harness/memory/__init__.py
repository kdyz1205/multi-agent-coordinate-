"""
Memory System — CrewAI-inspired, adapted for our harness.

Three memory types:
- ShortTermMemory: Current session context (in-memory)
- LongTermMemory: Cross-session knowledge (persisted to disk)
- SharedState: Live state shared between all agents in a crew

Design patterns learned from:
- CrewAI: Short-term + Long-term + Entity memory
- LangGraph: Shared state schema, checkpointing
- Anthropic: Keep it simple, compose with code
"""

from harness.memory.store import ShortTermMemory, LongTermMemory, SharedState

__all__ = ["ShortTermMemory", "LongTermMemory", "SharedState"]
