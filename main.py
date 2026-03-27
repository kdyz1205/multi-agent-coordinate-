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

    return Orchestrator(
        repo_dir=os.environ.get("REPO_DIR", "."),
        browser_config=browser_config,
        git_remote=os.environ.get("GIT_REMOTE", "origin"),
    )


async def main():
    """Start the Telegram bot with the full pipeline."""
    orchestrator = create_orchestrator()
    dispatcher = Dispatcher()
    bot = TelegramBot()

    @bot.on_message
    async def handle(msg: TelegramMessage) -> str:
        """Handle incoming Telegram messages."""
        task = msg.text

        # Special commands
        if task.startswith("/"):
            return handle_command(task, dispatcher)

        # Show dispatch plan first
        report = dispatcher.dispatch_report(task)
        bot.send_message(msg.chat_id, f"**Analyzing task...**\n\n```\n{report}\n```")

        # Execute the pipeline
        bot.send_message(msg.chat_id, "Executing... (this may take a few minutes)")
        result = await orchestrator.execute(task)

        # Return the summary
        return result.summary

    logger.info("Multi-Agent Coordinate bot starting...")
    bot.run()


def handle_command(command: str, dispatcher: Dispatcher) -> str:
    """Handle slash commands."""
    parts = command.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/start":
        return (
            "**Multi-Agent Coordinate Harness**\n\n"
            "Send me any task and I'll route it to the best AI:\n\n"
            "Level 1 (Simple Q&A) → GPT/Grok\n"
            "Level 2 (Moderate code) → Claude Web\n"
            "Level 3 (Heavy code) → Claude Code\n"
            "Level 4 (Multi-file) → Multiple Claude Code sessions\n"
            "Level 5 (Architecture) → Claude Code + Codex\n\n"
            "Commands:\n"
            "/analyze <task> — See how a task would be dispatched\n"
            "/status — Check system status\n"
            "/help — Show this message"
        )

    elif cmd == "/analyze" and len(parts) > 1:
        return f"```\n{dispatcher.dispatch_report(parts[1])}\n```"

    elif cmd == "/status":
        return (
            "**System Status**\n"
            "Gateway: Telegram ✓\n"
            "Dispatcher: Online ✓\n"
            "Browser Agents: Ready\n"
            "Git: Connected"
        )

    elif cmd == "/help":
        return handle_command("/start", dispatcher)

    else:
        return f"Unknown command: {cmd}\nUse /help for available commands."


if __name__ == "__main__":
    asyncio.run(main())
