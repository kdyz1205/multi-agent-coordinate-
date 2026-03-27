"""
Coder Agent — generates and iterates on code.

In a loop, the coder:
1. Reads instructions from the handoff
2. Generates or modifies code
3. Increases convergence score based on completeness
4. Passes result to next agent (or back to self)
"""

from harness.agent import Agent, AgentConfig
from harness.protocol import AgentRole, Handoff, Message, MessageType


def create_coder_agent(
    name: str = "coder",
    working_dir: str = ".",
    channel_type: str = "file",
    **kwargs,
) -> Agent:
    """Create a coder agent with a default handler."""
    config = AgentConfig(
        name=name,
        role=AgentRole.CODER,
        description="Generates and iterates on code based on instructions",
        capabilities=["python", "javascript", "typescript"],
        working_dir=working_dir,
        channel_type=channel_type,
        **kwargs,
    )
    agent = Agent(config)

    @agent.on_receive
    def handle(handoff: Handoff) -> Handoff:
        """
        Default coder handler — override this with your own logic.

        In a real scenario, this would call an LLM API to generate code.
        This template shows the structure for building your own.
        """
        # Read feedback from previous iteration
        feedback = ""
        for msg in reversed(handoff.messages):
            if msg.msg_type == MessageType.FEEDBACK:
                feedback = msg.content
                break

        # Placeholder: In production, call LLM here
        # response = call_llm(handoff.instructions, feedback, handoff.files)

        handoff.add_message(Message(
            msg_type=MessageType.STATUS,
            sender=name,
            receiver=handoff.target_agent or "reviewer",
            content=f"Code iteration {handoff.iteration} complete. "
                    f"{'Applied feedback: ' + feedback[:100] if feedback else 'Initial generation.'}",
        ))

        # Increment convergence (in production, compute from actual metrics)
        handoff.convergence_score = min(
            handoff.convergence_score + 0.15,
            1.0,
        )

        # Swap source/target for next round
        handoff.source_agent = name
        if handoff.target_agent == name:
            handoff.target_agent = "reviewer"

        return handoff

    return agent
