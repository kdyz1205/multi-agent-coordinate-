"""
Multi-Agent Coordinate — Main Entry Point

The full pipeline:
    Telegram → Dispatcher → Browser Agents → Git Merge → Result

Usage:
    # Start the bot:
    TELEGRAM_BOT_TOKEN=your_token python main.py

    # Or use directly in code:
    from pipeline import Orchestrator
    result = await Orchestrator().execute("帮我写一个 React 登录页面")
"""

import asyncio
import logging
import os

from gateway import TelegramBot, TelegramMessage
from dispatcher import Dispatcher
from pipeline import Orchestrator
from browser_agents import BrowserConfig
from tracker import QuotaTracker, SessionStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_orchestrator() -> Orchestrator:
    """Create the orchestrator with config from environment."""
    browser_config = BrowserConfig(
        headless=os.environ.get("HEADLESS", "false").lower() == "true",
        user_data_dir=os.environ.get("CHROME_USER_DATA", ""),
        timeout_ms=int(os.environ.get("TIMEOUT_MS", "120000")),
    )

    quota = QuotaTracker()
    sessions = SessionStore()

    return Orchestrator(
        repo_dir=os.environ.get("REPO_DIR", "."),
        browser_config=browser_config,
        git_remote=os.environ.get("GIT_REMOTE", "origin"),
        quota_tracker=quota,
        session_store=sessions,
    )


async def main():
    """Start the Telegram bot with the full pipeline."""
    orchestrator = create_orchestrator()
    bot = TelegramBot()

    @bot.on_message
    async def handle(msg: TelegramMessage) -> str:
        """Handle incoming Telegram messages."""
        task = msg.text

        # Special commands
        if task.startswith("/"):
            return handle_command(task, orchestrator)

        # Show dispatch plan first
        report = orchestrator.dispatcher.dispatch_report(task)
        bot.send_message(msg.chat_id, f"Analyzing task...\n\n{report}")

        # Execute the pipeline
        bot.send_message(msg.chat_id, "Executing... (this may take a few minutes)")
        result = await orchestrator.execute(task)

        # Return the summary
        return result.summary

    logger.info("Multi-Agent Coordinate bot starting...")
    bot.run()


def handle_command(command: str, orchestrator: Orchestrator) -> str:
    """Handle slash commands."""
    parts = command.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/start":
        return (
            "Multi-Agent Coordinate Harness\n\n"
            "Send me any task and I'll route it to the best AI:\n\n"
            "Level 1 (Simple Q&A) → GPT/Grok\n"
            "Level 2 (Moderate code) → Claude Web\n"
            "Level 3 (Heavy code) → Claude Code\n"
            "Level 4 (Multi-file) → Multiple Claude Code sessions\n"
            "Level 5 (Architecture) → Claude Code + Codex\n\n"
            "Commands:\n"
            "/analyze <task> — See dispatch plan\n"
            "/quota — Platform usage & availability\n"
            "/sessions — Active/paused sessions\n"
            "/resume — Resume paused sessions\n"
            "/status — System status\n"
            "/help — Show this message"
        )

    elif cmd == "/analyze" and len(parts) > 1:
        return orchestrator.dispatcher.dispatch_report(parts[1])

    elif cmd == "/quota":
        return orchestrator.quota.status_report()

    elif cmd == "/sessions":
        return orchestrator.sessions.status_report()

    elif cmd == "/resume":
        resumable = orchestrator.sessions.get_resumable()
        if not resumable:
            paused = orchestrator.sessions.get_paused()
            if paused:
                # Check if any paused sessions can now resume
                for s in paused:
                    if orchestrator.quota.is_available(s.platform):
                        s.mark_resumable()
                        orchestrator.sessions.update(s)
                resumable = orchestrator.sessions.get_resumable()

            if not resumable:
                return "No sessions to resume."

        lines = ["Resumable sessions:"]
        for s in resumable:
            lines.append(f"  {s.session_id} [{s.platform}] — {s.task[:50]}")
        lines.append("\nSend the original task again to resume automatically.")
        return "\n".join(lines)

    elif cmd == "/status":
        quota_summary = orchestrator.quota.status_report()
        session_summary = orchestrator.sessions.status_report()
        return (
            "System Status\n"
            "─────────────\n"
            f"Gateway: Telegram OK\n"
            f"Dispatcher: Online\n"
            f"Browser Agents: Ready\n"
            f"Git: Connected\n\n"
            f"{quota_summary}\n\n"
            f"{session_summary}"
        )

    elif cmd == "/help":
        return handle_command("/start", orchestrator)

    else:
        return f"Unknown command: {cmd}\nUse /help for available commands."


if __name__ == "__main__":
    asyncio.run(main())
