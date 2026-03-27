"""
web_ai.py — Browser automation for AI web interfaces.

DROP THIS FILE into your claude-tg-bot/ directory.

Uses Playwright to:
1. Open AI web pages (Claude, GPT, Grok, Claude Code)
2. Find the input box
3. Paste the user's prompt
4. Wait for the response
5. Extract the text/code

Supports PARALLEL multi-platform dispatch:
  Level 4-5 tasks → split into subtasks → send to different AIs simultaneously

IMPORTANT: You must be logged in to these AI platforms in Chrome.
Set CHROME_USER_DATA in .env to your Chrome profile directory:
  Windows: C:\\Users\\<you>\\AppData\\Local\\Google\\Chrome\\User Data
  macOS:   ~/Library/Application Support/Google/Chrome
"""

import asyncio
import logging
import re
import time
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ─── Task Difficulty Classification ──────────────────────────────────────────

DIFFICULTY_KEYWORDS = {
    5: ["architecture", "system design", "from scratch", "完整系统", "从零",
        "microservice", "infrastructure", "重构整个", "full application"],
    4: ["frontend and backend", "前端后端", "多个文件", "integrate", "merge",
        "full stack", "多个组件", "cross-session", "coordination", "combine"],
    3: ["refactor", "optimize", "complex", "authentication", "写一个完整",
        "重构", "api endpoint", "database", "test suite", "algorithm"],
    2: ["write", "create", "implement", "function", "component", "class",
        "写一个", "做一个", "帮我写", "code", "script", "fix", "bug"],
    1: ["what is", "how to", "explain", "什么是", "怎么", "为什么",
        "translate", "summarize", "list", "compare", "聊天", "你好"],
}

# Which platform for which difficulty level
PLATFORM_FOR_DIFFICULTY = {
    1: "grok",              # Simple Q&A → Grok (fastest, free)
    2: "claude_web",        # Single-file code → Claude
    3: "claude_code",       # Heavy code → Claude Code Web
    4: "parallel",          # Multi-file → parallel dispatch
    5: "parallel",          # Architecture → parallel dispatch
}

# For parallel dispatch — how to assign subtasks
PARALLEL_PLATFORM_POOL = ["claude_code", "claude_web", "gpt"]


# ─── Platform Selectors ─────────────────────────────────────────────────────

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
        "input_type": "prosemirror",
    },
    "claude_code": {
        "url": "https://claude.ai/code",
        "input": 'div.ProseMirror[contenteditable="true"], textarea, div[contenteditable="true"]',
        "send": 'button[aria-label="Send Message"], button[aria-label*="Send"]',
        "response": 'div[class*="font-claude-message"], div[class*="message"]',
        "stop": 'button[aria-label="Stop Response"]',
        "streaming": 'div[data-is-streaming="true"]',
        "code": 'pre code',
        "login_check": 'div.ProseMirror, textarea, div[contenteditable="true"]',
        "input_type": "prosemirror",
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
        "input_type": "contenteditable",
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
        "input_type": "textarea",
    },
}


class WebAIRouter:
    """Routes tasks to AI web interfaces via browser automation."""

    def __init__(self):
        self._browser = None
        self._context = None

    def classify_and_route(self, message: str) -> dict:
        """
        Classify difficulty and decide routing.

        Returns:
            {
                "platform": str,       # Primary platform
                "difficulty": int,     # 1-5
                "parallel": bool,      # Whether to use parallel dispatch
                "subtasks": [          # Only if parallel=True
                    {"platform": str, "prompt": str, "label": str},
                    ...
                ]
            }
        """
        msg_lower = message.lower()

        # Classify difficulty
        difficulty = 2  # Default: moderate
        for level in sorted(DIFFICULTY_KEYWORDS.keys(), reverse=True):
            for kw in DIFFICULTY_KEYWORDS[level]:
                if kw in msg_lower:
                    difficulty = level
                    break
            else:
                continue
            break

        platform = PLATFORM_FOR_DIFFICULTY[difficulty]

        # Handle parallel dispatch for Level 4-5
        if platform == "parallel":
            subtasks = self._split_for_parallel(message, difficulty)
            return {
                "platform": subtasks[0]["platform"] if subtasks else "claude_code",
                "difficulty": difficulty,
                "parallel": len(subtasks) > 1,
                "subtasks": subtasks,
            }

        return {
            "platform": platform,
            "difficulty": difficulty,
            "parallel": False,
            "subtasks": [],
        }

    def _split_for_parallel(self, message: str, difficulty: int) -> list[dict]:
        """
        Split a complex task into subtasks for parallel execution.

        Strategy:
        - Look for explicit numbered items
        - Look for "and" / "以及" / "还有" separators
        - Fallback: frontend/backend split
        - Last resort: single task on best platform
        """
        subtasks = []

        # Strategy 1: Explicit numbered items
        lines = message.split("\n")
        numbered = [l.strip() for l in lines if re.match(r"^\d+[\.\)]\s", l.strip())]
        if len(numbered) > 1:
            for i, item in enumerate(numbered):
                platform = PARALLEL_PLATFORM_POOL[i % len(PARALLEL_PLATFORM_POOL)]
                subtasks.append({
                    "platform": platform,
                    "prompt": item,
                    "label": f"Part {i+1}",
                })
            return subtasks

        # Strategy 2: "and" / "以及" separators
        parts = re.split(r"\band\b|以及|还有|同时", message)
        if len(parts) > 1:
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                platform = PARALLEL_PLATFORM_POOL[i % len(PARALLEL_PLATFORM_POOL)]
                subtasks.append({
                    "platform": platform,
                    "prompt": part,
                    "label": f"Part {i+1}",
                })
            return subtasks

        # Strategy 3: Frontend/Backend split
        msg_lower = message.lower()
        if any(kw in msg_lower for kw in ["frontend", "backend", "前端", "后端", "full stack", "fullstack"]):
            subtasks.append({
                "platform": "claude_code",
                "prompt": f"Frontend part of the following task. Focus ONLY on frontend (UI, components, styling):\n\n{message}",
                "label": "Frontend",
            })
            subtasks.append({
                "platform": "claude_web",
                "prompt": f"Backend part of the following task. Focus ONLY on backend (API, database, logic):\n\n{message}",
                "label": "Backend",
            })
            return subtasks

        # Fallback: single task on best platform
        return [{
            "platform": "claude_code",
            "prompt": message,
            "label": "Main",
        }]

    async def execute(self, platform: str, prompt: str) -> dict:
        """
        Execute a prompt on an AI web platform via browser.

        Returns:
            {
                "success": bool,
                "text": str,
                "code_blocks": list[str],
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

                    # Different input handling based on element type
                    if config.get("input_type") == "prosemirror":
                        # ProseMirror needs special handling — can't just insert_text
                        await page.keyboard.insert_text(prompt)
                    elif config.get("input_type") == "textarea":
                        await input_el.fill(prompt)
                    else:
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
                    rate_limit_phrases = [
                        "rate limit", "hit your limit", "usage cap",
                        "too many requests", "slow down", "limit reached",
                        "用量已达", "请稍后再试",
                    ]
                    if text:
                        text_lower = text.lower()
                        rate_limited = any(phrase in text_lower for phrase in rate_limit_phrases)

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
        # Method 1: Wait for stop button to disappear (streaming done)
        if config.get("stop"):
            try:
                for _ in range(max_wait // 2):
                    stop_btn = await page.query_selector(config["stop"])
                    if stop_btn is None:
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
