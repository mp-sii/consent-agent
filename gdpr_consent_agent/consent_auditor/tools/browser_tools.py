"""Browser tools — Playwright-based crawling and screenshot capture."""

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse


def _run_async(coro):
    """
    Run an async coroutine safely whether or not an event loop is already
    running (ADK runs its own loop, so asyncio.run() would raise RuntimeError).
    Spawns a dedicated thread — threads always start with no event loop.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()

# Domain pattern lists for request categorisation
ANALYTICS_DOMAINS = [
    "google-analytics.com",
    "analytics.google.com",
    "gtm.com",
    "googletagmanager.com",
    "segment.io",
    "segment.com",
    "mixpanel.com",
    "amplitude.com",
    "hotjar.com",
    "clarity.ms",
]

ADS_DOMAINS = [
    "doubleclick.net",
    "facebook.net",
    "googlesyndication.com",
    "googleadservices.com",
    "ads.",
    "adnxs.com",
    "criteo.com",
    "outbrain.com",
    "taboola.com",
    "linkedin.com/li/track",
    "bat.bing.com",
    "snap.licdn.com",
]

ESSENTIAL_DOMAINS = [
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.",
    "static.",
    "assets.",
]


def _categorise_request(url: str, page_origin: str) -> str:
    """Return category string for a request URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    page_parsed = urlparse(page_origin)
    page_domain = page_parsed.netloc.lower()

    # Same-origin = essential
    if domain == page_domain or domain.endswith("." + page_domain):
        return "essential"

    for ad_domain in ADS_DOMAINS:
        if ad_domain in domain:
            return "ads"

    for analytics_domain in ANALYTICS_DOMAINS:
        if analytics_domain in domain:
            return "analytics"

    for essential_domain in ESSENTIAL_DOMAINS:
        if essential_domain in domain or domain.startswith(essential_domain):
            return "essential"

    return "unknown"


async def _async_crawl_website(url: str) -> dict:
    from playwright.async_api import async_playwright

    network_requests = []
    error = None
    screenshot_b64 = ""
    cookies_before_consent = []
    has_datalayer = False
    has_tcf_api = False
    page_html_snippet = ""

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                accept_downloads=False,
                locale="en-US",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )

            page = await context.new_page()

            def on_request(request):
                category = _categorise_request(request.url, url)
                network_requests.append(
                    {
                        "url": request.url,
                        "method": request.method,
                        "resource_type": request.resource_type,
                        "category": category,
                    }
                )

            page.on("request", on_request)

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait for CMP scripts to initialise
            await page.wait_for_timeout(4000)

            # Capture HTML snippet (first 50 KB)
            html = await page.content()
            page_html_snippet = html[:51200]

            # Check for TCF API and dataLayer
            tcf_result = await page.evaluate("() => typeof window.__tcfapi")
            has_tcf_api = tcf_result != "undefined"

            dl_result = await page.evaluate("() => typeof window.dataLayer")
            has_datalayer = dl_result != "undefined"

            # Cookies set BEFORE any user consent action
            raw_cookies = await context.cookies()
            cookies_before_consent = [
                {
                    "name": c["name"],
                    "domain": c["domain"],
                    "path": c["path"],
                    "httpOnly": c["httpOnly"],
                    "secure": c["secure"],
                    "sameSite": c.get("sameSite", ""),
                    "expires": c.get("expires", -1),
                }
                for c in raw_cookies
            ]

            # Screenshot
            screenshot_bytes = await page.screenshot(full_page=False)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

            await browser.close()

    except Exception as exc:
        error = str(exc)

    return {
        "url": url,
        "screenshot_b64": screenshot_b64,
        "cookies_before_consent": cookies_before_consent,
        "network_requests": network_requests,
        "has_datalayer": has_datalayer,
        "has_tcf_api": has_tcf_api,
        "page_html_snippet": page_html_snippet,
        "error": error,
    }


def crawl_website(url: str) -> dict:
    """
    Visits a URL with a real Chromium browser. Captures:
    - All network requests grouped by category (analytics, ads, essential, unknown)
    - JavaScript dataLayer / window.__tcfapi presence
    - All cookies set BEFORE any user consent action
    - Raw HTML of the page (first 10KB for CMP detection)

    Args:
        url: Full URL including https:// e.g. "https://example.com"

    Returns:
        dict with keys: url, cookies_before_consent, network_requests (max 50),
                        has_datalayer, has_tcf_api, page_html_snippet (10 KB),
                        error (if any).
        Note: screenshot is stored internally and included in the final report.
    """
    result = _run_async(_async_crawl_website(url))
    # Save FULL result (including screenshot_b64) to shared_state for the report
    from consent_auditor import shared_state
    shared_state.set("url", url)
    shared_state.set("crawl", result)

    # Return a SLIM version to the LLM to avoid hitting token-per-minute quota.
    # screenshot_b64 alone can be 50 000+ tokens as a base64 string.
    requests = result.get("network_requests", [])
    return {
        "url": result["url"],
        "has_datalayer": result["has_datalayer"],
        "has_tcf_api": result["has_tcf_api"],
        "error": result["error"],
        "cookies_before_consent": result.get("cookies_before_consent", []),
        # Cap HTML at 10 KB — enough for CMP fingerprinting
        "page_html_snippet": result.get("page_html_snippet", "")[:10240],
        # Cap request list at 50 entries — enough for domain pattern matching
        "network_requests": requests[:50],
        "network_requests_total": len(requests),
    }


async def _async_take_scenario_screenshot(url: str, scenario_name: str) -> dict:
    from playwright.async_api import async_playwright

    screenshot_b64 = ""
    error = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                accept_downloads=False,
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            screenshot_bytes = await page.screenshot(full_page=False)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
            await browser.close()
    except Exception as exc:
        error = str(exc)

    return {
        "scenario_name": scenario_name,
        "screenshot_b64": screenshot_b64,
        "timestamp": datetime.utcnow().isoformat(),
        "error": error,
    }


def take_scenario_screenshot(url: str, scenario_name: str) -> dict:
    """
    Takes a screenshot labeled with scenario name.

    Args:
        url: Full URL to visit
        scenario_name: Label for this screenshot (e.g. "accept_all", "reject_all")

    Returns:
        dict with scenario_name, screenshot_b64, timestamp
    """
    return _run_async(_async_take_scenario_screenshot(url, scenario_name))
