"""
Quick Start — test the pipeline without Telegram.

Run this to see the dispatcher in action and test browser automation.
"""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dispatcher import Dispatcher
from browser_agents import BrowserConfig, get_browser_agent


def demo_dispatcher():
    """Show how tasks get classified and routed."""
    dispatcher = Dispatcher()

    tasks = [
        "什么是 React hooks?",
        "帮我写一个 Python 函数来计算斐波那契数列",
        "帮我重构这个认证模块，添加 JWT token 刷新机制",
        "帮我做一个完整的加密货币分析平台，前端用 React，后端用 FastAPI",
        "帮我从零设计一个微服务架构的电商系统",
    ]

    print("=" * 60)
    print("TASK DISPATCHER DEMO")
    print("=" * 60)

    for task in tasks:
        print(f"\nTask: {task}")
        print("-" * 40)
        print(dispatcher.dispatch_report(task))
        print()


async def demo_browser_agent():
    """
    Test browser automation with a single platform.
    Make sure you're logged in to the platform first!
    """
    config = BrowserConfig(
        headless=False,  # Show the browser
        user_data_dir="",  # Set to your Chrome profile path
    )

    agent = get_browser_agent("claude_web", config)
    result = await agent.execute("用 Python 写一个快速排序算法，加上详细注释")

    print("=" * 60)
    print("BROWSER AGENT RESULT")
    print("=" * 60)
    print(f"Success: {result.success}")
    print(f"Platform: {result.platform}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Code blocks: {len(result.code_blocks)}")

    for i, code in enumerate(result.code_blocks):
        print(f"\n--- Code Block {i + 1} ---")
        print(code[:500])


if __name__ == "__main__":
    # Always run dispatcher demo (no browser needed)
    demo_dispatcher()

    # Uncomment to test browser automation:
    # asyncio.run(demo_browser_agent())
