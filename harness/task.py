"""
Task System — CrewAI-inspired task definitions with context dependencies.

A Task is a specific piece of work assigned to an agent, with:
- Description of what needs to be done
- Expected output format
- Context dependencies (output of other tasks)
- Assigned agent
- Tools required

Tasks form a DAG (directed acyclic graph) where output of one
task flows as context to downstream tasks.

Patterns learned from:
- CrewAI: Task context chaining, expected_output, delegation
- LangGraph: Shared state schema, conditional routing
- Anthropic: Prompt chaining, task decomposition
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DELEGATED = "delegated"


@dataclass
class TaskResult:
    """Output from a completed task."""
    output: str = ""
    code_blocks: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)  # path → content
    score: float = 0.0           # Quality score 0-1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Task:
    """
    A unit of work for an agent.

    Usage:
        research = Task(
            description="Research React best practices for auth",
            expected_output="A summary of top 3 auth patterns",
            agent="researcher",
        )
        code = Task(
            description="Implement login page based on research",
            expected_output="Complete React component code",
            agent="coder",
            context=[research],  # Gets research output as context
        )
    """
    description: str
    agent: str                    # Name of assigned agent
    expected_output: str = ""     # What the output should look like
    context: list[Task] = field(default_factory=list)  # Upstream dependencies
    tools: list[str] = field(default_factory=list)     # Required tools
    allow_delegation: bool = False  # Can this agent delegate to others?

    # Runtime state
    status: TaskStatus = TaskStatus.PENDING
    result: TaskResult | None = None
    delegated_to: str = ""
    attempts: int = 0
    max_attempts: int = 3

    # Timing
    started_at: float = 0
    completed_at: float = 0

    # Identity
    task_id: str = ""

    def __post_init__(self):
        if not self.task_id:
            self.task_id = f"task_{id(self)}_{int(time.time())}"

    def get_context_text(self) -> str:
        """Build context string from upstream task results."""
        if not self.context:
            return ""
        parts = []
        for upstream in self.context:
            if upstream.result and upstream.result.output:
                parts.append(
                    f"--- Context from '{upstream.description[:50]}' ---\n"
                    f"{upstream.result.output}\n"
                )
        return "\n".join(parts)

    def build_prompt(self) -> str:
        """Build the full prompt including context from upstream tasks."""
        parts = []

        # Add upstream context
        ctx = self.get_context_text()
        if ctx:
            parts.append("## Previous work (use as context):\n" + ctx)

        # Add task description
        parts.append(f"## Your task:\n{self.description}")

        # Add expected output
        if self.expected_output:
            parts.append(f"## Expected output:\n{self.expected_output}")

        return "\n\n".join(parts)

    def complete(self, result: TaskResult):
        """Mark task as completed."""
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.completed_at = time.time()

    def fail(self, error: str = ""):
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.result = TaskResult(output=f"FAILED: {error}")
        self.completed_at = time.time()

    def delegate(self, to_agent: str):
        """Delegate this task to another agent."""
        self.status = TaskStatus.DELEGATED
        self.delegated_to = to_agent

    @property
    def is_ready(self) -> bool:
        """Can this task start? (all upstream dependencies completed)"""
        return all(
            t.status == TaskStatus.COMPLETED
            for t in self.context
        )

    @property
    def duration(self) -> float:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return 0


def decompose_task(description: str, agent_names: list[str]) -> list[Task]:
    """
    Simple rule-based task decomposition.
    Splits a complex description into subtasks.

    For smarter decomposition, use an LLM call (see orchestrator).
    """
    import re

    # Check for explicit numbered items
    lines = description.strip().split("\n")
    numbered = [l.strip() for l in lines if re.match(r"^\d+[\.\)]\s", l.strip())]
    if numbered:
        tasks = []
        for i, line in enumerate(numbered):
            agent = agent_names[i % len(agent_names)]
            tasks.append(Task(description=line, agent=agent))
        # Chain context: each task gets previous as context
        for i in range(1, len(tasks)):
            tasks[i].context = [tasks[i - 1]]
        return tasks

    # Check for "and" / comma separation
    parts = re.split(r"\band\b|以及|还有|同时", description)
    if len(parts) > 1:
        tasks = []
        for i, part in enumerate(parts):
            agent = agent_names[i % len(agent_names)]
            tasks.append(Task(description=part.strip(), agent=agent))
        return tasks

    # Single task
    return [Task(description=description, agent=agent_names[0])]
