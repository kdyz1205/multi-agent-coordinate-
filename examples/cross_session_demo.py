"""
Cross-Session Collaboration Demo

This example shows how two Claude Code sessions can collaborate
on the same project using the git channel.

Session A: Generates a React component
Session B: Integrates it into the main website

Run in Session A first, then Session B.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness import Harness, Agent, AgentConfig, Handoff
from harness.protocol import AgentRole
from harness.channels import GitChannel

# ============================================================
# SESSION A — The Producer
# Run this in the session that generates code
# ============================================================

def session_a():
    """Session A: Generate code and hand it off via git."""
    # Create a coder agent
    config = AgentConfig(
        name="dashboard-coder",
        role=AgentRole.CODER,
        description="Creates a crypto dashboard component",
        capabilities=["react", "javascript", "css"],
        channel_type="git",
        channel_config={"repo_dir": ".", "remote": "origin"},
    )
    coder = Agent(config)

    # Create a handoff with the generated code
    handoff = coder.create_handoff(
        target="site-integrator",
        instructions="Integrate this dashboard component into the main website. "
                     "Place it in src/components/ and add it to the App.jsx router.",
    )

    # Add files to the handoff
    handoff.add_file(
        path="src/components/CryptoDashboard.jsx",
        content="""
import React, { useState, useEffect } from 'react';

export default function CryptoDashboard() {
    const [prices, setPrices] = useState({});

    useEffect(() => {
        // Fetch crypto prices
        fetch('https://api.example.com/prices')
            .then(res => res.json())
            .then(data => setPrices(data));
    }, []);

    return (
        <div className="dashboard">
            <h1>Crypto Dashboard</h1>
            {Object.entries(prices).map(([coin, price]) => (
                <div key={coin} className="price-card">
                    <span>{coin}</span>
                    <span>${price}</span>
                </div>
            ))}
        </div>
    );
}
""",
        language="javascript",
        insert_point="",  # New file, no insert point needed
    )

    handoff.add_file(
        path="src/components/CryptoDashboard.css",
        content="""
.dashboard {
    padding: 2rem;
    max-width: 800px;
    margin: 0 auto;
}
.price-card {
    display: flex;
    justify-content: space-between;
    padding: 1rem;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    margin-bottom: 0.5rem;
}
""",
        language="css",
    )

    # Send via git channel
    channel = GitChannel(repo_dir=".", remote="origin")
    channel.send(handoff)
    print(f"Handoff sent! ID: {handoff.handoff_id}")
    print(f"Target: {handoff.target_agent}")
    print(f"Files: {[f.path for f in handoff.files]}")


# ============================================================
# SESSION B — The Consumer
# Run this in the session that integrates the code
# ============================================================

def session_b():
    """Session B: Receive the handoff and integrate into the website."""
    from agents import create_integrator_agent

    # Create an integrator agent
    integrator = create_integrator_agent(
        name="site-integrator",
        target_dir=".",
        channel_type="git",
    )

    # Receive the handoff
    channel = GitChannel(repo_dir=".", remote="origin")
    handoff = channel.receive("site-integrator")

    if handoff is None:
        print("No handoffs found. Make sure Session A has pushed.")
        return

    print(f"Received handoff from: {handoff.source_agent}")
    print(f"Instructions: {handoff.instructions}")
    print(f"Files: {[f.path for f in handoff.files]}")

    # Process the handoff (integrator writes files to target dir)
    result = integrator.process(handoff)

    # Print integration results
    for msg in result.messages:
        print(f"[{msg.msg_type.value}] {msg.content}")


# ============================================================
# Usage
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "receive":
        session_b()
    else:
        session_a()
