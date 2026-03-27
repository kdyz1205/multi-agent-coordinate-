"""
Evaluator-Optimizer Loop — Anthropic's recommended pattern for quality.

Two roles:
- Optimizer: generates/improves output
- Evaluator: scores and provides feedback

Loop continues until:
- Quality threshold met
- Max iterations reached
- Evaluator says "good enough"

Patterns learned from:
- Anthropic: Evaluator-Optimizer is the key quality pattern
- CrewAI: Delegation + feedback between agents
- LangGraph: Conditional routing based on evaluation
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Callable, Any

from harness.task import Task, TaskResult, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class EvalFeedback:
    """Feedback from the evaluator."""
    score: float              # 0.0 to 1.0
    passed: bool              # Meets threshold?
    feedback: str             # What to improve
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class EvalLoopResult:
    """Result of an evaluator-optimizer loop."""
    final_output: str
    final_score: float
    iterations: int
    converged: bool
    history: list[dict] = field(default_factory=list)  # Each iteration's output + feedback
    duration: float = 0


class EvaluatorOptimizer:
    """
    Runs an optimize → evaluate → feedback → optimize loop.

    Usage:
        loop = EvaluatorOptimizer(
            optimize_fn=my_generator,
            evaluate_fn=my_evaluator,
            threshold=0.85,
            max_iterations=5,
        )
        result = loop.run(task)

    The optimize_fn and evaluate_fn can be:
    - A function that calls an LLM
    - A function that runs linters/tests
    - A function that uses browser automation
    - Any callable that takes (task, feedback) and returns output
    """

    def __init__(
        self,
        optimize_fn: Callable[[Task, str], TaskResult],
        evaluate_fn: Callable[[Task, TaskResult], EvalFeedback],
        threshold: float = 0.85,
        max_iterations: int = 5,
        on_iteration: Callable[[int, TaskResult, EvalFeedback], None] | None = None,
    ):
        self.optimize = optimize_fn
        self.evaluate = evaluate_fn
        self.threshold = threshold
        self.max_iterations = max_iterations
        self.on_iteration = on_iteration

    def run(self, task: Task) -> EvalLoopResult:
        """Run the evaluator-optimizer loop."""
        start = time.time()
        history = []
        feedback_text = ""  # No feedback on first iteration

        result = None
        feedback = None
        for i in range(self.max_iterations):
            logger.info(f"Eval-Opt iteration {i + 1}/{self.max_iterations}")

            # Optimize (generate/improve)
            result = self.optimize(task, feedback_text)

            # Evaluate
            feedback = self.evaluate(task, result)

            # Record history
            history.append({
                "iteration": i + 1,
                "output_preview": result.output[:200] if result.output else "",
                "score": feedback.score,
                "passed": feedback.passed,
                "feedback": feedback.feedback,
                "issues": feedback.issues,
            })

            # Callback
            if self.on_iteration:
                self.on_iteration(i + 1, result, feedback)

            # Check convergence
            if feedback.passed or feedback.score >= self.threshold:
                logger.info(f"Converged at iteration {i + 1} (score={feedback.score:.2f})")
                return EvalLoopResult(
                    final_output=result.output,
                    final_score=feedback.score,
                    iterations=i + 1,
                    converged=True,
                    history=history,
                    duration=time.time() - start,
                )

            # Prepare feedback for next iteration
            feedback_text = self._build_feedback_prompt(feedback)

        # Max iterations reached
        logger.warning(f"Max iterations ({self.max_iterations}) reached without convergence")
        return EvalLoopResult(
            final_output=result.output if result else "",
            final_score=feedback.score if feedback else 0,
            iterations=self.max_iterations,
            converged=False,
            history=history,
            duration=time.time() - start,
        )

    def _build_feedback_prompt(self, feedback: EvalFeedback) -> str:
        """Build a feedback prompt for the optimizer."""
        parts = [f"Score: {feedback.score:.2f}/1.0 — needs improvement."]

        if feedback.feedback:
            parts.append(f"Feedback: {feedback.feedback}")

        if feedback.issues:
            parts.append("Issues found:")
            for issue in feedback.issues:
                parts.append(f"  - {issue}")

        if feedback.suggestions:
            parts.append("Suggestions:")
            for sug in feedback.suggestions:
                parts.append(f"  - {sug}")

        return "\n".join(parts)


# ─── Built-in Evaluators ─────────────────────────────────────────────────────

def code_quality_evaluator(task: Task, result: TaskResult) -> EvalFeedback:
    """
    Simple code quality evaluator using heuristics.
    Replace with LLM-based evaluation for production.
    """
    code = result.output
    issues = []
    score = 1.0

    if not code.strip():
        return EvalFeedback(score=0, passed=False, feedback="Empty output", issues=["No code generated"])

    # Basic heuristics
    if "import *" in code:
        issues.append("Wildcard import detected")
        score -= 0.1

    if "TODO" in code or "FIXME" in code:
        issues.append("Contains TODO/FIXME markers")
        score -= 0.05

    if "print(" in code and "def test" not in code:
        issues.append("Debug print statements found")
        score -= 0.05

    if len(code) < 50:
        issues.append("Output seems too short")
        score -= 0.2

    # Check for common patterns
    if "try:" in code and "except:" in code and "except Exception" not in code:
        issues.append("Bare except clause (should specify exception type)")
        score -= 0.1

    if "password" in code.lower() and "hash" not in code.lower():
        issues.append("Password handling without hashing")
        score -= 0.15

    score = max(0, min(1.0, score))
    passed = score >= 0.85 and len(issues) == 0

    return EvalFeedback(
        score=score,
        passed=passed,
        feedback=f"{len(issues)} issues found" if issues else "Code looks good",
        issues=issues,
    )


def completeness_evaluator(task: Task, result: TaskResult) -> EvalFeedback:
    """Check if the output addresses what was asked."""
    output = result.output.lower()
    description = task.description.lower()
    expected = task.expected_output.lower() if task.expected_output else ""

    issues = []
    score = 0.5  # Start at 50%

    # Check if output mentions key terms from the task
    task_words = set(description.split()) - {"the", "a", "an", "is", "to", "and", "or", "in", "for"}
    matches = sum(1 for w in task_words if w in output)
    relevance = matches / max(len(task_words), 1)
    score += relevance * 0.3

    # Check length adequacy
    if len(result.output) > 100:
        score += 0.1
    if len(result.output) > 500:
        score += 0.1

    # Check for code if expected
    if any(kw in description for kw in ["write", "code", "implement", "function", "写", "代码"]):
        if result.code_blocks or "def " in output or "function" in output or "class " in output:
            score += 0.1
        else:
            issues.append("Expected code but none found")
            score -= 0.2

    score = max(0, min(1.0, score))
    passed = score >= 0.85

    return EvalFeedback(
        score=score,
        passed=passed,
        feedback="Output adequately addresses the task" if passed else "Output may be incomplete",
        issues=issues,
    )
