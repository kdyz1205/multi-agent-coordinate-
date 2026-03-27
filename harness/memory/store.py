"""
Memory Store — three-layer memory system.

ShortTermMemory: In-memory, current session only. Fast.
LongTermMemory: Persisted to disk (JSON). Survives restarts.
SharedState: Live dictionary shared between agents. The "scratchpad".

Pattern: LangGraph's Shared State Schema + CrewAI's Memory types.
"""

from __future__ import annotations

import json
import time
import logging
from pathlib import Path
from typing import Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class ShortTermMemory:
    """
    In-memory context for the current session.
    Stores recent messages, task outputs, and agent interactions.
    Automatically trims old entries to prevent unbounded growth.
    """

    def __init__(self, max_entries: int = 100):
        self.max_entries = max_entries
        self._store: list[dict] = []

    def add(self, role: str, content: str, metadata: dict = None):
        """Add an entry to short-term memory."""
        self._store.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
            "metadata": metadata or {},
        })
        # Trim if over limit
        if len(self._store) > self.max_entries:
            self._store = self._store[-self.max_entries:]

    def get_recent(self, n: int = 10) -> list[dict]:
        """Get the N most recent entries."""
        return self._store[-n:]

    def get_by_role(self, role: str) -> list[dict]:
        """Get all entries from a specific role/agent."""
        return [e for e in self._store if e["role"] == role]

    def search(self, keyword: str) -> list[dict]:
        """Simple keyword search across all entries."""
        keyword = keyword.lower()
        return [e for e in self._store if keyword in e["content"].lower()]

    def to_context_string(self, n: int = 5) -> str:
        """Convert recent memory to a context string for prompts."""
        recent = self.get_recent(n)
        parts = []
        for entry in recent:
            parts.append(f"[{entry['role']}]: {entry['content'][:200]}")
        return "\n".join(parts)

    def clear(self):
        self._store.clear()

    def __len__(self):
        return len(self._store)


class LongTermMemory:
    """
    Persistent memory that survives restarts.
    Stores task results, learned patterns, and cross-session knowledge.
    Uses simple JSON files — no database needed.
    """

    def __init__(self, path: str = ".harness_state/long_term_memory.json"):
        self.path = Path(path)
        self._store: dict[str, list[dict]] = defaultdict(list)
        self._load()

    def store(self, category: str, content: str, metadata: dict = None):
        """Store a piece of knowledge."""
        self._store[category].append({
            "content": content,
            "timestamp": time.time(),
            "metadata": metadata or {},
        })
        self._save()

    def recall(self, category: str, n: int = 5) -> list[dict]:
        """Recall recent entries from a category."""
        return self._store.get(category, [])[-n:]

    def recall_all(self) -> dict[str, list[dict]]:
        """Get all stored knowledge."""
        return dict(self._store)

    def search(self, keyword: str) -> list[dict]:
        """Search across all categories."""
        keyword = keyword.lower()
        results = []
        for category, entries in self._store.items():
            for entry in entries:
                if keyword in entry["content"].lower():
                    results.append({**entry, "category": category})
        return results

    def store_task_result(self, task_description: str, result: str, score: float = 0):
        """Store a completed task result for future reference."""
        self.store("task_results", result, {
            "task": task_description[:200],
            "score": score,
        })

    def store_feedback(self, feedback: str, context: str = ""):
        """Store evaluation feedback for learning."""
        self.store("feedback", feedback, {"context": context[:200]})

    def get_similar_tasks(self, description: str, n: int = 3) -> list[dict]:
        """Find previously completed similar tasks (simple keyword match)."""
        words = set(description.lower().split())
        scored = []
        for entry in self._store.get("task_results", []):
            task_words = set(entry.get("metadata", {}).get("task", "").lower().split())
            overlap = len(words & task_words)
            if overlap > 0:
                scored.append((overlap, entry))
        scored.sort(key=lambda x: -x[0])
        return [entry for _, entry in scored[:n]]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Limit each category to 500 entries
        trimmed = {k: v[-500:] for k, v in self._store.items()}
        self.path.write_text(json.dumps(trimmed, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._store = defaultdict(list, data)
            logger.info(f"Long-term memory loaded: {sum(len(v) for v in self._store.values())} entries")
        except Exception as e:
            logger.warning(f"Failed to load long-term memory: {e}")


class SharedState:
    """
    Live shared state between agents — the "scratchpad".

    Pattern from LangGraph: All agents read/write to a shared state object.
    This enables real-time coordination without explicit message passing.

    Usage:
        state = SharedState()
        state.set("research_results", "React auth uses JWT...")
        # Later, another agent:
        research = state.get("research_results")
    """

    def __init__(self):
        self._state: dict[str, Any] = {}
        self._history: list[dict] = []  # Audit trail
        self._checkpoints: list[dict] = []

    def set(self, key: str, value: Any, agent: str = ""):
        """Set a value in shared state."""
        self._state[key] = value
        self._history.append({
            "action": "set",
            "key": key,
            "agent": agent,
            "timestamp": time.time(),
            "value_preview": str(value)[:100],
        })

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from shared state."""
        return self._state.get(key, default)

    def update(self, data: dict, agent: str = ""):
        """Merge a dictionary into shared state."""
        self._state.update(data)
        for key in data:
            self._history.append({
                "action": "update",
                "key": key,
                "agent": agent,
                "timestamp": time.time(),
            })

    def delete(self, key: str):
        """Remove a key."""
        self._state.pop(key, None)

    def keys(self) -> list[str]:
        return list(self._state.keys())

    def checkpoint(self, label: str = ""):
        """Save a snapshot of current state (like LangGraph checkpointing)."""
        import copy
        self._checkpoints.append({
            "label": label,
            "timestamp": time.time(),
            "state": copy.deepcopy(self._state),
        })

    def restore(self, index: int = -1):
        """Restore state from a checkpoint."""
        if self._checkpoints:
            self._state = self._checkpoints[index]["state"]

    def get_history(self, n: int = 10) -> list[dict]:
        """Get recent state changes (audit trail)."""
        return self._history[-n:]

    def __contains__(self, key):
        return key in self._state

    def __repr__(self):
        return f"SharedState(keys={list(self._state.keys())})"
