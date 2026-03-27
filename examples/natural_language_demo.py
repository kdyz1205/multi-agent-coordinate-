"""
Natural Language Harness Demo

Shows how to create a full harness from a plain English description.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness import Harness


def main():
    # Create a harness from natural language
    harness = Harness.from_natural_language("""
        Create a coder and a reviewer agent.
        They should alternate back and forth in a ping-pong loop.
        The coder writes Python code, the reviewer checks for quality.
        Loop up to 8 times or until score above 0.9.
        Use file-based communication.
    """)

    # See what was generated
    print("Generated harness config:")
    print(harness.to_yaml())

    print(f"\nStatus: {harness.status()}")

    # Wire up handlers before running
    for name, agent in harness.agents.items():
        @agent.on_receive
        def handle(handoff, agent_name=name):
            print(f"  [{agent_name}] Processing iteration {handoff.iteration}")
            handoff.convergence_score += 0.12
            handoff.convergence_score = min(handoff.convergence_score, 1.0)
            return handoff

    # Run it
    print("\nRunning harness...")
    result = harness.run()
    print(f"\nDone! Converged: {result.converged}, Iterations: {result.iterations}")


if __name__ == "__main__":
    main()
