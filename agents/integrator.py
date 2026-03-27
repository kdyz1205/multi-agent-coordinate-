"""
Integrator Agent — merges code from multiple agents into a unified codebase.

The integrator:
1. Reads files from the handoff
2. Determines where each file belongs in the target project
3. Resolves conflicts if multiple agents modified the same file
4. Produces the merged result
"""

from pathlib import Path

from harness.agent import Agent, AgentConfig
from harness.protocol import AgentRole, Handoff, Message, MessageType, FilePayload


def create_integrator_agent(
    name: str = "integrator",
    target_dir: str = ".",
    channel_type: str = "file",
    **kwargs,
) -> Agent:
    """Create an integrator agent that merges code into a target project."""
    config = AgentConfig(
        name=name,
        role=AgentRole.INTEGRATOR,
        description="Merges code from multiple sources into a unified project",
        capabilities=["code_integration", "conflict_resolution"],
        working_dir=target_dir,
        channel_type=channel_type,
        **kwargs,
    )
    agent = Agent(config)

    @agent.on_receive
    def handle(handoff: Handoff) -> Handoff:
        """
        Default integrator handler.

        Writes files from the handoff into the target directory,
        respecting insert_point hints when provided.
        """
        target = Path(target_dir)
        integrated = []
        conflicts = []

        for fp in handoff.files:
            dest = target / fp.path
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dest.exists():
                existing = dest.read_text(encoding="utf-8")
                if existing != fp.content:
                    if fp.insert_point:
                        # Insert at specified point
                        if fp.insert_point in existing:
                            merged = existing.replace(
                                fp.insert_point,
                                fp.insert_point + "\n" + fp.content,
                            )
                            dest.write_text(merged, encoding="utf-8")
                            integrated.append(f"{fp.path} (inserted at '{fp.insert_point}')")
                        else:
                            conflicts.append(f"{fp.path}: insert point '{fp.insert_point}' not found")
                    else:
                        # Full replacement
                        dest.write_text(fp.content, encoding="utf-8")
                        integrated.append(f"{fp.path} (replaced)")
                else:
                    integrated.append(f"{fp.path} (unchanged)")
            else:
                dest.write_text(fp.content, encoding="utf-8")
                integrated.append(f"{fp.path} (created)")

        # Report results
        report = f"Integration complete: {len(integrated)} files processed."
        if conflicts:
            report += f"\nConflicts ({len(conflicts)}):\n" + "\n".join(f"- {c}" for c in conflicts)

        handoff.add_message(Message(
            msg_type=MessageType.MERGE_REQUEST if conflicts else MessageType.CONVERGENCE,
            sender=name,
            receiver=handoff.source_agent or "coder",
            content=report,
        ))

        handoff.convergence_score = 1.0 if not conflicts else 0.5
        return handoff

    return agent
