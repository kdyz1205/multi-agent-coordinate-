"""
web_ai.py — Browser automation for AI web interfaces.

DROP THIS FILE into your claude-tg-bot/ directory.

Uses the bot's existing Playwright setup (browser_agent.py) to:
1. Open AI web pages (Claude, GPT, Grok)
2. Find the input box
3. Paste the user's prompt
4. Wait for the response
5. Extract the text/code

This is the "hands" of the harness — it types into AI chat boxes for you.

IMPORTANT: You must be logged in to these AI platforms in Chrome.
Set CHROME_USER_DATA in .env to your Chrome profile directory:
  Windows: C:\\Users\\<you>\\AppData\\Local\\Google\\Chrome\\User Data
  macOS:   ~/Library/Application Support/Google/Chrome
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ─── Task Difficulty Classification ──────────────────────────────────────────

DIFFICULTY_KEYWORDS = {
    5: ["architecture", "system design", "from scratch", "完整系统", "从零", "microservice"],
    4: ["frontend and backend", "前端后端", "多个文件", "integrate", "merge", "full stack"],
    3: ["refactor", "optimize", "complex", "authentication", "写一个完整", "重构", "api endpoint"],
    2: ["write", "create", "function", "component", "写一个", "做一个", "帮我写", "code", "fix"],
    1: ["what is", "how to", "explain", "什么是", "怎么", "为什么", "translate", "summarize"],
}

# Which platform for which difficulty level
PLATFORM_FOR_DIFFICULTY = {
    1: "grok",          # Simple Q&A → Grok (free)
    2: "claude_web",    # Moderate code → Claude
    3: "claude_web",    # Heavy code → Claude
    4: "claude_web",    # Multi-file → Claude (single session for now)
    5: "claude_web",    # Architecture → Claude
}


# ─── Platform Selectors ─────────────────────────────────────────────────────
# CSS selectors for each AI platform's UI elements.
# UPDATE THESE if the platform's UI changes.

PLATFORM_CONFIG = {
    "claude_web": {
        "url": "https://claude.ai/new",
        "input": 'div.ProseMirror[contenteditable="true"], div[contenteditable="true"]',
        "send": 'button[aria-label="Send Message"], button[aria-label*="Send"]',
        "response": 'div[class*="font-claude-message"]',
        "stop": 'button[aria-label="Stop Response"]',
        "streaming": 'div[data-is-streaming="true"]',
        "code": 'pre code',
        "login_check": 'div.ProseMirror, div[contenteditable="true"]',
    },
    "gpt": {
        "url": "https://chatgpt.com",
        "input": 'div#prompt-textarea',
        "send": 'button[data-testid="send-button"]',
        "response": 'div.markdown',
        "stop": 'button[aria-label="Stop generating"]',
        "streaming": None,
        "code": 'div.markdown pre code',
        "login_check": 'div#prompt-textarea',
    },
    "grok": {
        "url": "https://grok.com",
        "input": 'textarea, div[contenteditable="true"]',
        "send": 'button[type="submit"], button[aria-label*="Send"]',
        "response": 'div[class*="message"], div[class*="response"], div[class*="markdown"]',
        "stop": None,
        "streaming": None,
        "code": 'pre code',
        "login_check": 'textarea, div[contenteditable="true"]',
    },
}


class WebAIRouter:
    """Routes tasks to AI web interfaces via browser automation."""

    def __init__(self):
        self._browser = None
        self._context = None

    def classify_and_route(self, message: str) -> tuple[str, int]:
        """Classify difficulty and pick platform. Returns (platform, difficulty)."""
        msg_lower = message.lower()

        # Check from hardest to easiest
        for level in sorted(DIFFICULTY_KEYWORDS.keys(), reverse=True):
            for kw in DIFFICULTY_KEYWORDS[level]:
                if kw in msg_lower:
                    platform = PLATFORM_FOR_DIFFICULTY[level]
                    return platform, level

        # Default: moderate → claude_web
        return "claude_web", 2

    async def execute(self, platform: str, prompt: str) -> dict:
        """
        Execute a prompt on an AI web platform via browser.

        Returns:
            {
                "success": bool,
                "text": str,          # Full response text
                "code_blocks": [],    # Extracted code blocks
                "rate_limited": bool,
                "error": str,
                "duration": float,
            }
        """
        config = PLATFORM_CONFIG.get(platform)
        if not config:
            return {"success": False, "text": "", "code_blocks": [],
                    "rate_limited": False, "error": f"Unknown platform: {platform}", "duration": 0}

        start = time.time()

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as pw:
                # Launch with user profile to reuse login sessions
                import os
                user_data = os.environ.get("CHROME_USER_DATA", "")

                if user_data:
                    ctx = await pw.chromium.launch_persistent_context(
                        user_data,
                        headless=False,
                        slow_mo=50,
                    )
                    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                else:
                    browser = await pw.chromium.launch(headless=False, slow_mo=50)
                    ctx = await browser.new_context()
                    page = await ctx.new_page()

                try:
                    # Navigate
                    await page.goto(config["url"], wait_until="networkidle", timeout=30000)

                    # Check login
                    try:
                        await page.wait_for_selector(config["login_check"], timeout=15000)
                    except Exception:
                        return {"success": False, "text": "", "code_blocks": [],
                                "rate_limited": False,
                                "error": f"未登录 {platform}。请先在 Chrome 中手动登录。",
                                "duration": time.time() - start}

                    # Find input and type
                    input_el = await page.wait_for_selector(config["input"], timeout=10000)
                    await input_el.click()
                    await page.keyboard.insert_text(prompt)
                    await asyncio.sleep(0.5)

                    # Send
                    try:
                        send_btn = await page.wait_for_selector(config["send"], timeout=3000)
                        await send_btn.click()
                    except Exception:
                        await page.keyboard.press("Enter")

                    # Wait for response
                    await asyncio.sleep(3)
                    text = await self._wait_for_response(page, config)

                    # Check for rate limit in response
                    rate_limited = False
                    if text and ("rate limit" in text.lower() or "hit your limit" in text.lower()
                                 or "usage cap" in text.lower()):
                        rate_limited = True

                    # Extract code blocks
                    code_blocks = []
                    if config["code"]:
                        code_els = await page.query_selector_all(config["code"])
                        for el in code_els:
                            code = await el.inner_text()
                            if code.strip():
                                code_blocks.append(code.strip())

                    return {
                        "success": bool(text and not rate_limited),
                        "text": text or "",
                        "code_blocks": code_blocks,
                        "rate_limited": rate_limited,
                        "error": "" if not rate_limited else "Rate limited",
                        "duration": time.time() - start,
                    }

                finally:
                    await ctx.close()

        except ImportError:
            return {"success": False, "text": "", "code_blocks": [],
                    "rate_limited": False,
                    "error": "Playwright 未安装。运行: pip install playwright && playwright install chromium",
                    "duration": time.time() - start}

        except Exception as e:
            logger.error(f"Browser automation error on {platform}: {e}", exc_info=True)
            return {"success": False, "text": "", "code_blocks": [],
                    "rate_limited": False,
                    "error": str(e)[:300],
                    "duration": time.time() - start}

    async def _wait_for_response(self, page, config: dict, max_wait: int = 180) -> str:
        """Wait for the AI to finish generating and return the text."""
        # Method 1: Wait for stop button to disappear
        if config.get("stop"):
            try:
                for _ in range(max_wait // 2):
                    stop_btn = await page.query_selector(config["stop"])
                    if stop_btn is None:
                        # Double check streaming
                        if config.get("streaming"):
                            streaming = await page.query_selector(config["streaming"])
                            if streaming is None:
                                break
                        else:
                            break
                    await asyncio.sleep(2)
            except Exception:
                pass

        # Method 2: Wait for text to stabilize
        last_text = ""
        stable_count = 0

        for _ in range(max_wait // 2):
            await asyncio.sleep(2)
            try:
                elements = await page.query_selector_all(config["response"])
                if not elements:
                    continue
                current_text = await elements[-1].inner_text()

                if current_text == last_text and current_text:
                    stable_count += 1
                    if stable_count >= 2:
                        return current_text
                else:
                    stable_count = 0
                    last_text = current_text
            except Exception:
                continue

        return last_text
