"""
Reviewer Agent — reviews code and provides feedback.

In a loop, the reviewer:
1. Reads code from the handoff
2. Evaluates quality (structure, bugs, style)
3. Provides feedback as a FEEDBACK message
4. Adjusts convergence score based on quality assessment
"""

from harness.agent import Agent, AgentConfig
from harness.protocol import AgentRole, Handoff, Message, MessageType


def create_reviewer_agent(
    name: str = "reviewer",
    working_dir: str = ".",
    channel_type: str = "file",
    **kwargs,
) -> Agent:
    """Create a reviewer agent with a default handler."""
    config = AgentConfig(
        name=name,
        role=AgentRole.REVIEWER,
        description="Reviews code and provides constructive feedback",
        capabilities=["code_review", "quality_assessment"],
        working_dir=working_dir,
        channel_type=channel_type,
        **kwargs,
    )
    agent = Agent(config)

    @agent.on_receive
    def handle(handoff: Handoff) -> Handoff:
        """
        Default reviewer handler — override with your own logic.

        In production, this would call an LLM to review the code,
        or run static analysis tools (pylint, eslint, etc.).
        """
        # Analyze the files in the handoff
        file_count = len(handoff.files)
        issues_found = []

        for fp in handoff.files:
            if not fp.content.strip():
                issues_found.append(f"{fp.path}: Empty file")
            if fp.language == "python" and "import *" in fp.content:
                issues_found.append(f"{fp.path}: Wildcard import detected")

        # Generate feedback
        if issues_found:
            feedback = "Issues found:\n" + "\n".join(f"- {i}" for i in issues_found)
            score_delta = 0.05  # Small improvement
        else:
            feedback = f"Code looks good. {file_count} files reviewed, no major issues."
            score_delta = 0.2  # Bigger improvement

        handoff.add_message(Message(
            msg_type=MessageType.FEEDBACK,
            sender=name,
            receiver=handoff.source_agent or "coder",
            content=feedback,
        ))

        # Update convergence
        handoff.convergence_score = min(
            handoff.convergence_score + score_delta,
            1.0,
        )

        # Swap direction — send back to original source
        original_source = handoff.source_agent
        handoff.source_agent = name
        handoff.target_agent = original_source if original_source != name else "coder"

        return handoff

    return agent
