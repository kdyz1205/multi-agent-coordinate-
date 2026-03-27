"""
Orchestrator — the complete pipeline that ties everything together.

Flow:
    User (Telegram) → Dispatcher (classify + split) → Browser Agents (execute) → Git (merge) → Result

This is the "brain" of the harness. It:
1. Receives a task from the gateway (Telegram)
2. Dispatches to the right AI platform(s)
3. Executes via browser automation
4. Collects results
5. If multi-agent: merges via git
6. Returns the final result
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dispatcher import Dispatcher, TaskRoute, Difficulty
from browser_agents import get_browser_agent, BrowserConfig, AgentResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Final result from the full pipeline."""
    success: bool
    task: str
    difficulty: str
    platforms_used: list[str]
    agent_results: list[AgentResult]
    merged: bool = False
    git_branch: str = ""
    total_duration: float = 0
    summary: str = ""


class Orchestrator:
    """
    The master orchestrator.

    Usage:
        orch = Orchestrator(repo_dir="/path/to/project")
        result = await orch.execute("帮我写一个 React 登录页面")
    """

    def __init__(
        self,
        repo_dir: str = ".",
        browser_config: BrowserConfig | None = None,
        dispatcher: Dispatcher | None = None,
        git_remote: str = "origin",
    ):
        self.repo_dir = Path(repo_dir)
        self.browser_config = browser_config or BrowserConfig()
        self.dispatcher = dispatcher or Dispatcher()
        self.git_remote = git_remote

    async def execute(self, task: str, context: str = "") -> PipelineResult:
        """
        Full pipeline execution.

        1. Dispatch (classify difficulty, split if needed)
        2. Execute on browser agent(s)
        3. Git merge if multi-agent
        4. Return result
        """
        start = time.time()

        # Step 1: Dispatch
        route = self.dispatcher.dispatch(task, context)
        logger.info(f"Dispatched: {route.difficulty.name} → {route.platform}")

        # Step 2: Execute
        if route.metadata.get("needs_multi_agent"):
            agent_results = await self._execute_multi_agent(route)
        else:
            agent_results = [await self._execute_single_agent(route)]

        # Step 3: Git merge (if multi-agent)
        merged = False
        git_branch = ""
        if route.metadata.get("needs_git_merge") and len(agent_results) > 1:
            git_branch = self._git_merge(route, agent_results)
            merged = True

        # Step 4: Build result
        success = any(r.success for r in agent_results)
        summary = self._build_summary(route, agent_results, merged)

        return PipelineResult(
            success=success,
            task=task,
            difficulty=route.difficulty.name,
            platforms_used=[r.platform for r in agent_results],
            agent_results=agent_results,
            merged=merged,
            git_branch=git_branch,
            total_duration=time.time() - start,
            summary=summary,
        )

    async def _execute_single_agent(self, route: TaskRoute) -> AgentResult:
        """Execute task on a single browser agent."""
        agent = get_browser_agent(route.platform, self.browser_config)
        return await agent.execute(route.task)

    async def _execute_multi_agent(self, route: TaskRoute) -> list[AgentResult]:
        """Execute subtasks on multiple browser agents in parallel."""
        platforms = route.metadata.get("all_platforms", [route.platform])
        subtasks = route.subtasks

        # Pair subtasks with platforms
        tasks = []
        for i, subtask in enumerate(subtasks):
            platform = platforms[i % len(platforms)]
            agent = get_browser_agent(platform, self.browser_config)
            tasks.append(agent.execute(subtask))

        # Execute all in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        agent_results = []
        for r in results:
            if isinstance(r, Exception):
                agent_results.append(AgentResult(
                    success=False,
                    output="",
                    error=str(r),
                ))
            else:
                agent_results.append(r)

        return agent_results

    def _git_merge(self, route: TaskRoute, results: list[AgentResult]) -> str:
        """Merge multi-agent results via git."""
        branch_name = f"harness/multi-{int(time.time())}"

        try:
            # Create a new branch
            self._run_git("checkout", "-b", branch_name)

            # Write each agent's code output to files
            for i, result in enumerate(results):
                if not result.success or not result.code_blocks:
                    continue

                for j, code in enumerate(result.code_blocks):
                    filename = f"output_{result.platform}_{i}_{j}.py"
                    filepath = self.repo_dir / filename
                    filepath.write_text(code, encoding="utf-8")
                    self._run_git("add", str(filepath))

            # Commit
            self._run_git(
                "commit", "-m",
                f"harness: multi-agent output for '{route.task[:50]}...'"
            )

            # Push
            for attempt in range(4):
                r = self._run_git("push", "-u", self.git_remote, branch_name, check=False)
                if r.returncode == 0:
                    break
                time.sleep(2 ** (attempt + 1))

            return branch_name

        except Exception as e:
            logger.error(f"Git merge failed: {e}")
            return ""

    def _run_git(self, *args, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + list(args),
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            check=check,
        )

    def _build_summary(
        self, route: TaskRoute, results: list[AgentResult], merged: bool
    ) -> str:
        """Build a human-readable summary for Telegram response."""
        lines = [
            f"**Task completed**",
            f"Difficulty: Level {route.difficulty} ({route.difficulty.name})",
            f"Platforms: {', '.join(r.platform for r in results)}",
        ]

        for i, r in enumerate(results):
            status = "OK" if r.success else f"FAIL ({r.error[:50]})"
            lines.append(f"Agent {i+1} [{r.platform}]: {status} ({r.duration_seconds:.1f}s)")
            if r.code_blocks:
                lines.append(f"  Code blocks: {len(r.code_blocks)}")

        if merged:
            lines.append(f"Git merge: branch created")

        total_time = sum(r.duration_seconds for r in results)
        lines.append(f"Total time: {total_time:.1f}s")

        return "\n".join(lines)
