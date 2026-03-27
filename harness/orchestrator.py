"""
Orchestrator-Worker — the production-standard multi-agent pattern.

From Anthropic's guide: "The most-deployed multi-agent pattern in production."

How it works:
1. Orchestrator receives task
2. Decomposes into subtasks (using Task system)
3. Routes each subtask to the best worker agent
4. Workers execute independently
5. Orchestrator collects results, evaluates, decides next steps
6. Loop until all subtasks complete and quality threshold met

This combines:
- CrewAI's hierarchical process (manager agent)
- LangGraph's supervisor pattern (central coordinator)
- Anthropic's orchestrator-worker recommendation
"""

from __future__ import annotations

import time
import logging
from typing import Any, Callable

from harness.agent import Agent, AgentConfig
from harness.task import Task, TaskResult, TaskStatus, decompose_task
from harness.evaluator import EvaluatorOptimizer, EvalFeedback, completeness_evaluator
from harness.memory import ShortTermMemory, LongTermMemory, SharedState
from harness.protocol import AgentRole

logger = logging.getLogger(__name__)


class OrchestratorWorker:
    """
    The production-grade orchestration pattern.

    Usage:
        # Define workers
        workers = {
            "coder": coder_agent,
            "reviewer": reviewer_agent,
            "tester": tester_agent,
        }

        # Create orchestrator
        orch = OrchestratorWorker(workers=workers)

        # Execute a complex task
        result = orch.execute("Build a React dashboard with auth")
    """

    def __init__(
        self,
        workers: dict[str, Agent],
        decompose_fn: Callable[[str, list[str]], list[Task]] | None = None,
        evaluate_fn: Callable[[Task, TaskResult], EvalFeedback] | None = None,
        max_rounds: int = 3,
        quality_threshold: float = 0.8,
    ):
        self.workers = workers
        self.decompose = decompose_fn or decompose_task
        self.evaluate = evaluate_fn or completeness_evaluator
        self.max_rounds = max_rounds
        self.quality_threshold = quality_threshold

        # Memory
        self.memory = ShortTermMemory()
        self.long_memory = LongTermMemory()
        self.state = SharedState()

    def execute(self, task_description: str) -> OrchestratorResult:
        """
        Full orchestrator-worker execution cycle.

        1. Decompose task into subtasks
        2. Assign to workers
        3. Execute all ready tasks
        4. Evaluate results
        5. If quality insufficient, create follow-up tasks
        6. Repeat until done
        """
        start = time.time()
        agent_names = list(self.workers.keys())

        # Step 1: Decompose
        tasks = self.decompose(task_description, agent_names)
        logger.info(f"Decomposed into {len(tasks)} subtasks")
        self.memory.add("orchestrator", f"Decomposed: {[t.description[:50] for t in tasks]}")

        # Step 2-5: Execute in rounds
        all_results = []
        for round_num in range(self.max_rounds):
            logger.info(f"Round {round_num + 1}/{self.max_rounds}")
            self.state.checkpoint(f"round_{round_num + 1}_start")

            # Find ready tasks
            ready = [t for t in tasks if t.status == TaskStatus.PENDING and t.is_ready]
            if not ready:
                # Check if all done
                if all(t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) for t in tasks):
                    break
                continue

            # Execute ready tasks
            for task in ready:
                result = self._execute_task(task)
                all_results.append((task, result))

                # Store in shared state
                self.state.set(
                    f"result_{task.task_id}",
                    result.output[:500] if result else "",
                    agent=task.agent,
                )

            # Evaluate all completed tasks
            quality_ok = True
            for task in tasks:
                if task.status == TaskStatus.COMPLETED and task.result:
                    feedback = self.evaluate(task, task.result)
                    if not feedback.passed and task.attempts < task.max_attempts:
                        # Retry: create a follow-up task with feedback
                        logger.info(f"Task '{task.description[:30]}...' needs improvement (score={feedback.score:.2f})")
                        task.status = TaskStatus.PENDING
                        task.description = (
                            f"{task.description}\n\n"
                            f"PREVIOUS ATTEMPT FEEDBACK: {feedback.feedback}\n"
                            f"Issues: {', '.join(feedback.issues)}"
                        )
                        quality_ok = False

            if quality_ok:
                break

        # Compile final result
        completed_tasks = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        failed_tasks = [t for t in tasks if t.status == TaskStatus.FAILED]

        # Store in long-term memory
        for task in completed_tasks:
            if task.result:
                self.long_memory.store_task_result(
                    task.description, task.result.output, task.result.score
                )

        return OrchestratorResult(
            success=len(failed_tasks) == 0,
            tasks=tasks,
            completed=len(completed_tasks),
            failed=len(failed_tasks),
            total_rounds=round_num + 1,
            duration=time.time() - start,
            final_state=dict(self.state._state),
        )

    def _execute_task(self, task: Task) -> TaskResult | None:
        """Execute a single task on the assigned worker."""
        worker = self.workers.get(task.agent)
        if not worker:
            logger.error(f"No worker named '{task.agent}'")
            task.fail(f"No worker named '{task.agent}'")
            return None

        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        task.attempts += 1

        try:
            # Build the full prompt with context
            prompt = task.build_prompt()

            # Add memory context
            memory_ctx = self.memory.to_context_string(3)
            if memory_ctx:
                prompt = f"## Recent context:\n{memory_ctx}\n\n{prompt}"

            # Add similar past tasks
            similar = self.long_memory.get_similar_tasks(task.description, 2)
            if similar:
                past_ctx = "\n".join(
                    f"- Previous: {s['metadata'].get('task', '')[:80]}"
                    for s in similar
                )
                prompt = f"## Past similar work:\n{past_ctx}\n\n{prompt}"

            # Execute via the worker's handler
            from harness.protocol import Handoff
            handoff = Handoff(
                source_agent="orchestrator",
                target_agent=worker.name,
                instructions=prompt,
            )
            result_handoff = worker.process(handoff)

            # Extract result
            result = TaskResult(
                output=result_handoff.instructions or "Task processed",
                score=result_handoff.convergence_score,
            )
            task.complete(result)

            # Record in memory
            self.memory.add(worker.name, f"Completed: {task.description[:50]}")

            return result

        except Exception as e:
            logger.error(f"Task execution failed: {e}", exc_info=True)
            task.fail(str(e))
            return None

    def add_worker(self, name: str, agent: Agent):
        """Add a worker agent."""
        self.workers[name] = agent


class OrchestratorResult:
    """Result of an orchestrator execution."""

    def __init__(
        self,
        success: bool,
        tasks: list[Task],
        completed: int,
        failed: int,
        total_rounds: int,
        duration: float,
        final_state: dict,
    ):
        self.success = success
        self.tasks = tasks
        self.completed = completed
        self.failed = failed
        self.total_rounds = total_rounds
        self.duration = duration
        self.final_state = final_state

    def summary(self) -> str:
        lines = [
            f"Orchestrator Result: {'SUCCESS' if self.success else 'PARTIAL'}",
            f"Tasks: {self.completed} completed, {self.failed} failed",
            f"Rounds: {self.total_rounds}",
            f"Duration: {self.duration:.1f}s",
        ]
        for task in self.tasks:
            status = task.status.value
            score = task.result.score if task.result else 0
            lines.append(f"  [{status}] {task.description[:60]}... (score={score:.2f})")
        return "\n".join(lines)
