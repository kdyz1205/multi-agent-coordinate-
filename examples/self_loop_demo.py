"""
Self-Loop Demo

Shows how a single agent can iterate on its own output
until convergence (e.g., refining code quality).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness import Harness
from harness.agent import Agent, AgentConfig
from harness.protocol import AgentRole, Handoff, Message, MessageType
from harness.loop import LoopController, LoopMode


def main():
    # Create a self-improving coder agent
    config = AgentConfig(
        name="self-improver",
        role=AgentRole.CODER,
        max_iterations=7,
        convergence_threshold=0.85,
    )
    agent = Agent(config)

    @agent.on_receive
    def improve(handoff: Handoff) -> Handoff:
        """Each iteration improves the code quality score."""
        iteration = handoff.iteration
        print(f"  Iteration {iteration}: score = {handoff.convergence_score:.2f}")

        # Simulate improvement (in production, call LLM + run linters)
        handoff.convergence_score += 0.15
        handoff.convergence_score = min(handoff.convergence_score, 1.0)

        handoff.add_message(Message(
            msg_type=MessageType.STATUS,
            sender="self-improver",
            receiver="self-improver",
            content=f"Iteration {iteration}: Refactored code, score now {handoff.convergence_score:.2f}",
        ))
        return handoff

    # Run the self-loop
    controller = LoopController(
        mode=LoopMode.SELF,
        max_iterations=7,
        convergence_threshold=0.85,
    )

    print("Starting self-improvement loop...")
    result = controller.run(agent=agent, initial_handoff=Handoff())

    print(f"\nResult:")
    print(f"  Converged: {result.converged}")
    print(f"  Iterations: {result.iterations}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    print(f"  Final score: {result.final_handoff.convergence_score:.2f}")


if __name__ == "__main__":
    main()
