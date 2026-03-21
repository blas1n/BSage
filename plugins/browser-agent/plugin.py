"""Browser automation Plugin — scrape web pages, fill forms, interact with web interfaces."""

import re
from typing import Any

from bsage.plugin import plugin

# CSS selector validation: allow only safe characters for Playwright locators.
# Blocks backticks, braces, backslashes, and other injection-prone characters.
_SELECTOR_SAFE_RE = re.compile(r"^[a-zA-Z0-9\s\.\#\-\_\[\]\=\'\"\:\(\)\,\*\>\+\~]+$")


@plugin(
    name="browser-agent",
    version="1.0.0",
    category="process",
    description="Automate browser tasks — web scraping, form filling, data extraction",
    trigger={"type": "on_demand", "hint": "browse web, scrape page, fill form, extract data"},
    credentials=[
        {
            "name": "headless",
            "description": "Run browser in headless mode (default: true)",
            "required": False,
        },
    ],
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to visit (e.g. https://example.com)",
            },
            "task": {
                "type": "string",
                "description": (
                    "What to do (e.g. 'extract all article titles',"
                    " 'fill login form', 'click the submit button')"
                ),
            },
            "extract_selector": {
                "type": "string",
                "description": (
                    "CSS selector to extract specific content (optional, e.g. '.article-title')"
                ),
            },
            "wait_for_selector": {
                "type": "string",
                "description": "CSS selector to wait for before proceeding (optional)",
            },
        },
        "required": ["url", "task"],
    },
)
async def execute(context) -> dict:
    """Execute browser automation task and extract/act on web content."""
    data = context.input_data or {}
    url = data.get("url", "").strip()
    task = data.get("task", "").strip()
    extract_selector = data.get("extract_selector", "").strip()
    wait_for_selector = data.get("wait_for_selector", "").strip()

    if not url:
        return {"success": False, "error": "url is required"}
    if not task:
        return {"success": False, "error": "task is required"}

    # Validate CSS selectors
    selector_pairs = [
        ("extract_selector", extract_selector),
        ("wait_for_selector", wait_for_selector),
    ]
    for sel_name, sel_val in selector_pairs:
        if sel_val and not _SELECTOR_SAFE_RE.match(sel_val):
            return {
                "success": False,
                "error": f"invalid {sel_name}: disallowed characters",
            }

    # Validate URL scheme — only http/https allowed
    if url.startswith(("http://", "https://")):
        pass
    elif "://" in url:
        # Reject data:, javascript:, file:, etc.
        return {"success": False, "error": "only http:// and https:// URLs are allowed"}
    else:
        url = "https://" + url

    # Get credentials
    creds = context.credentials or {}
    headless = creds.get("headless", "true").lower() in ("true", "1", "yes")

    try:
        result = await _browser_task(
            url,
            task,
            extract_selector,
            wait_for_selector,
            headless,
            context.logger,
        )

        # Write to action log
        await context.garden.write_action(
            "browser-agent",
            f"Browsed: {url}\nTask: {task}",
        )

        # Write full result to seed
        await context.garden.write_seed(
            "browser-agent",
            {
                "url": url,
                "task": task,
                "success": result["success"],
                "content": result.get("content", ""),
                "page_title": result.get("page_title", ""),
            },
        )

        return result

    except Exception as e:
        context.logger.exception("browser_task_error", url=url, error=str(e))
        return {"success": False, "error": f"Browser task failed: {e}"}


async def _browser_task(
    url: str,
    task: str,
    extract_selector: str,
    wait_for_selector: str,
    headless: bool,
    logger: Any,
) -> dict:
    """Execute browser automation task using Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "success": False,
            "error": (
                "playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            ),
        }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        try:
            # Navigate to URL
            logger.info("browser_navigate", url=url)
            await page.goto(url, wait_until="load", timeout=30000)

            # Wait for specific selector if provided
            if wait_for_selector:
                logger.info("browser_wait", selector=wait_for_selector)
                await page.wait_for_selector(wait_for_selector, timeout=10000)

            # Get page title
            page_title = await page.title()

            # Extract content based on selector or task
            if extract_selector:
                # Use CSS selector to extract
                try:
                    content = await page.locator(extract_selector).all_text_contents()
                    extracted = "\n".join(content) if content else "No content found"
                except Exception as e:
                    extracted = f"Selector error: {e}"
            else:
                # Get full page text content
                extracted = await page.content()

            # Truncate if too long
            if len(extracted) > 50000:
                extracted = extracted[:50000] + f"\n... (truncated, {len(extracted)} total chars)"

            logger.info("browser_extract_success", title=page_title, content_len=len(extracted))

            return {
                "success": True,
                "url": url,
                "page_title": page_title,
                "content": extracted,
            }

        finally:
            await browser.close()


@execute.setup
def setup(cred_store: Any) -> None:
    """Configure browser-agent preferences."""
    import asyncio

    import click

    click.echo("Browser Agent Setup")
    headless = click.confirm("  Run in headless mode (recommended)?", default=True)

    data = {
        "headless": "true" if headless else "false",
    }

    asyncio.run(cred_store.store("browser-agent", data))
    click.echo("  Preferences saved.")


@execute.notify
async def notify(context) -> dict:
    """Send extracted content summary back to user's active channel."""
    content = (context.input_data or {}).get("content", "")
    title = (context.input_data or {}).get("page_title", "")
    url = (context.input_data or {}).get("url", "")

    if not content:
        return {"sent": False, "reason": "no content to send"}

    # Summarize long content
    max_len = 2000
    summary = content if len(content) <= max_len else content[:max_len] + "\n... (truncated)"

    message = f"Page: {title or url}\n\n{summary}"

    if context.notify:
        await context.notify.send(message)
        return {"sent": True, "length": len(message)}

    return {"sent": False, "reason": "no notification channel available"}
