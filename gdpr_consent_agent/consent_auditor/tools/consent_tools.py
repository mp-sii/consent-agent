"""Consent intelligence tools — CMP detection, signal extraction, scenario testing."""

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
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

# Known tracker domains used when checking cookies set before consent
TRACKING_DOMAINS = [
    "google-analytics.com",
    "analytics.google.com",
    "doubleclick.net",
    "facebook.net",
    "googlesyndication.com",
    "googleadservices.com",
    "segment.io",
    "segment.com",
    "hotjar.com",
    "clarity.ms",
    "mixpanel.com",
    "amplitude.com",
    "adnxs.com",
    "criteo.com",
    "bat.bing.com",
]


# ---------------------------------------------------------------------------
# Tool 3: detect_cmp_and_banner
# ---------------------------------------------------------------------------

def detect_cmp_and_banner(page_html_snippet: str, network_requests: list[dict]) -> dict:
    """
    Analyzes the page HTML and network requests to identify:
    - Which CMP is in use (OneTrust, Cookiebot, TrustArc, Usercentrics,
      Quantcast, Axeptio, Didomi, CookieYes, custom, or none)
    - Whether a consent banner is present and visible
    - Banner position (modal/overlay/bottom-bar/top-bar)
    - Whether the banner blocks page interaction (overlay=True/False)
    - Available consent categories presented to user
    - Whether "Reject All" button exists at top level (GDPR requirement)

    Args:
        page_html_snippet: First 50KB of page HTML
        network_requests: List of dicts from crawl_website

    Returns:
        dict with: cmp_vendor, cmp_detected (bool), banner_visible (bool),
                   banner_type, blocks_interaction (bool),
                   consent_categories (list), reject_all_available (bool),
                   gdpr_compliant_banner_structure (bool)
    """
    html_lower = page_html_snippet.lower()
    request_domains = " ".join(r.get("url", "") for r in network_requests).lower()

    cmp_vendor = "none"
    cmp_detected = False

    # CMP fingerprint detection
    if "onetrust" in html_lower or "optanon" in html_lower:
        cmp_vendor = "OneTrust"
        cmp_detected = True
    elif "cookiebot" in request_domains or "cookieconsent" in html_lower or "cookiebot" in html_lower:
        cmp_vendor = "Cookiebot"
        cmp_detected = True
    elif "trustarc.com" in request_domains or "truste.com" in request_domains:
        cmp_vendor = "TrustArc"
        cmp_detected = True
    elif "usercentrics" in html_lower or "usercentrics" in request_domains:
        cmp_vendor = "Usercentrics"
        cmp_detected = True
    elif "didomi" in html_lower or "didomi" in request_domains:
        cmp_vendor = "Didomi"
        cmp_detected = True
    elif "axeptio" in html_lower or "axeptio" in request_domains:
        cmp_vendor = "Axeptio"
        cmp_detected = True
    elif "cookieyes" in html_lower:
        cmp_vendor = "CookieYes"
        cmp_detected = True
    elif "__cmp" in html_lower and "quantcast" in request_domains:
        cmp_vendor = "Quantcast"
        cmp_detected = True
    elif (
        "cookie" in html_lower and "consent" in html_lower
        and ("banner" in html_lower or "popup" in html_lower or "notice" in html_lower)
    ):
        cmp_vendor = "custom"
        cmp_detected = True

    # Banner visibility heuristics
    banner_keywords = [
        "cookie-banner", "cookie_banner", "cookiebanner",
        "consent-banner", "consent_banner",
        "cookie-notice", "cookie_notice",
        "cookie-popup", "gdpr-banner",
        "cc-banner", "cc-window",
        "consent-modal", "privacy-banner",
    ]
    banner_visible = cmp_detected or any(kw in html_lower for kw in banner_keywords)

    # Banner type / position
    banner_type = "unknown"
    if "modal" in html_lower or "overlay" in html_lower:
        banner_type = "modal"
    elif "bottom" in html_lower and "cookie" in html_lower:
        banner_type = "bottom-bar"
    elif "top" in html_lower and "cookie" in html_lower:
        banner_type = "top-bar"
    elif banner_visible:
        banner_type = "banner"

    blocks_interaction = banner_type == "modal"

    # Consent categories
    category_patterns = [
        r"analytics|statistik|statistic",
        r"marketing|advertising|advertisement",
        r"functional|functionality|preferences|personali[sz]ation",
        r"necessary|essential|required|strictly",
        r"social.media|social media",
    ]
    consent_categories = []
    for pattern in category_patterns:
        if re.search(pattern, html_lower):
            label = pattern.split("|")[0].title()
            if label not in consent_categories:
                consent_categories.append(label)

    # Reject All availability
    reject_patterns = [
        "reject all", "reject-all", "rejectall",
        "decline all", "decline-all",
        "refuse all", "refuse-all",
        "deny all", "deny-all",
        "ablehnen",   # German
        "tout refuser",  # French
    ]
    reject_all_available = any(p in html_lower for p in reject_patterns)

    # Vendor-specific reject selectors that indicate top-level availability
    vendor_reject_ids = [
        "onetrust-reject-all-handler",
        "CybotCookiebotDialogBodyButtonDecline",
        "CybotCookiebotDialogBodyLevelButtonDecline",
    ]
    if any(vid.lower() in html_lower for vid in vendor_reject_ids):
        reject_all_available = True

    # GDPR compliant banner structure:
    # banner present + reject all available at top level
    gdpr_compliant_banner_structure = banner_visible and reject_all_available

    result = {
        "cmp_vendor": cmp_vendor,
        "cmp_detected": cmp_detected,
        "banner_visible": banner_visible,
        "banner_type": banner_type,
        "blocks_interaction": blocks_interaction,
        "consent_categories": consent_categories,
        "reject_all_available": reject_all_available,
        "gdpr_compliant_banner_structure": gdpr_compliant_banner_structure,
    }
    from consent_auditor import shared_state
    shared_state.set("cmp_detection", result)
    return result


# ---------------------------------------------------------------------------
# Tool 4: extract_consent_mode_signals
# ---------------------------------------------------------------------------

_CONSENT_INTERCEPT_SCRIPT = """
    window._consentModeCalls = [];
    // Intercept gtag()
    const origGtag = window.gtag;
    window.gtag = function() {
        window._consentModeCalls.push({source: 'gtag', args: Array.from(arguments)});
        if (origGtag) origGtag.apply(this, arguments);
    };
    // Intercept dataLayer.push
    if (!window.dataLayer) window.dataLayer = [];
    const origPush = Array.prototype.push;
    window.dataLayer.push = function() {
        const item = arguments[0];
        if (item && (item.event === 'default' || item[0] === 'consent' ||
            (typeof item === 'object' && JSON.stringify(item).includes('consent')))) {
            window._consentModeCalls.push({source: 'dataLayer', args: item});
        }
        return origPush.apply(this, arguments);
    };
"""

CONSENT_TYPES = [
    "analytics_storage",
    "ad_storage",
    "ad_user_data",
    "ad_personalization",
    "functionality_storage",
    "personalization_storage",
    "security_storage",
]


async def _async_extract_consent_mode_signals(url: str) -> dict:
    from playwright.async_api import async_playwright

    error = None
    consent_mode_detected = False
    consent_mode_version = "none"
    default_states: dict = {}
    has_wait_for_update = False
    wait_for_update_ms = 0

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
            )
            page = await context.new_page()
            await page.add_init_script(_CONSENT_INTERCEPT_SCRIPT)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            calls = await page.evaluate("() => window._consentModeCalls || []")

            # Parse consent calls
            for call in calls:
                source = call.get("source", "")
                args = call.get("args", [])

                if source == "gtag" and isinstance(args, list):
                    if len(args) >= 3 and args[0] == "consent" and args[1] == "default":
                        consent_mode_detected = True
                        settings = args[2] if isinstance(args[2], dict) else {}
                        for ct in CONSENT_TYPES:
                            if ct in settings:
                                default_states[ct] = settings[ct]
                        if "wait_for_update" in settings:
                            has_wait_for_update = True
                            wait_for_update_ms = int(settings["wait_for_update"])

                elif source == "dataLayer" and isinstance(args, dict):
                    if args.get(0) == "consent" or args.get("event") == "consent":
                        consent_mode_detected = True

            # Determine version
            if consent_mode_detected:
                has_v2_fields = (
                    "ad_user_data" in default_states
                    or "ad_personalization" in default_states
                )
                consent_mode_version = "v2" if has_v2_fields else "v1"

            await browser.close()

    except Exception as exc:
        error = str(exc)

    all_denied = (
        consent_mode_detected
        and bool(default_states)
        and all(v == "denied" for v in default_states.values())
    )

    # Consent mode compliant = v2 + all denied by default
    gdpr_consent_mode_compliant = (
        consent_mode_detected
        and consent_mode_version == "v2"
        and all_denied
    )

    return {
        "consent_mode_detected": consent_mode_detected,
        "consent_mode_version": consent_mode_version,
        "default_states": default_states,
        "has_wait_for_update": has_wait_for_update,
        "wait_for_update_ms": wait_for_update_ms,
        "all_denied_by_default": all_denied,
        "gdpr_consent_mode_compliant": gdpr_consent_mode_compliant,
        "error": error,
    }


def extract_consent_mode_signals(url: str) -> dict:
    """
    Loads the page and reads Google Consent Mode v2 signals from dataLayer.
    Checks for gtag('consent', 'default', {...}) and update calls, and
    which consent types are set / what their default state is.

    Args:
        url: Website URL

    Returns:
        dict with: consent_mode_detected (bool), consent_mode_version (str: v1/v2/none),
                   default_states (dict of type->granted/denied),
                   has_wait_for_update (bool), wait_for_update_ms (int),
                   all_denied_by_default (bool), gdpr_consent_mode_compliant (bool)
    """
    result = _run_async(_async_extract_consent_mode_signals(url))
    from consent_auditor import shared_state
    shared_state.set("consent_mode", result)
    return result


# ---------------------------------------------------------------------------
# Tool 5: run_consent_scenarios
# ---------------------------------------------------------------------------

_ACCEPT_SELECTORS = {
    "OneTrust": ["#onetrust-accept-btn-handler", ".onetrust-accept-btn-handler"],
    "Cookiebot": ["#CybotCookiebotDialogBodyButtonAccept", ".CybotCookiebotDialogBodyButton[id*='Accept']"],
    "generic": [],
}

_REJECT_SELECTORS = {
    "OneTrust": ["#onetrust-reject-all-handler", ".onetrust-reject-all-handler"],
    "Cookiebot": [
        "#CybotCookiebotDialogBodyButtonDecline",
        ".CybotCookiebotDialogBodyLevelButtonDecline",
    ],
    "generic": [],
}

_ACCEPT_TEXT_PATTERNS = re.compile(r"accept all|accept cookies|agree|allow all|i agree|got it", re.I)
_REJECT_TEXT_PATTERNS = re.compile(r"reject all|decline all|refuse all|deny all|no thanks", re.I)
_CLOSE_PATTERNS = re.compile(r"close|dismiss|×|✕|✖", re.I)


async def _click_button(page, vendor: str, selector_map: dict, text_pattern: re.Pattern) -> bool:
    """Try vendor-specific selectors first, then text-based fallback."""
    selectors = selector_map.get(vendor, []) + selector_map.get("generic", [])
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click(timeout=3000)
                return True
        except Exception:
            pass

    # Text-based fallback
    try:
        btn = page.get_by_role("button").filter(has_text=text_pattern).first
        if await btn.is_visible(timeout=3000):
            await btn.click(timeout=3000)
            return True
    except Exception:
        pass
    return False


async def _run_scenario(
    playwright_instance, url: str, vendor: str, scenario: str
) -> dict:
    from playwright.async_api import async_playwright  # noqa: F401 (used via instance)

    network_requests = []
    cookies_after = []
    consent_mode_update = {}
    violations = []
    action_taken = "none"

    browser = await playwright_instance.chromium.launch(
        headless=True, args=["--no-sandbox"]
    )
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

    # Inject consent mode spy
    await page.add_init_script(_CONSENT_INTERCEPT_SCRIPT)

    def on_request(request):
        from consent_auditor.tools.browser_tools import _categorise_request
        cat = _categorise_request(request.url, url)
        network_requests.append({"url": request.url, "category": cat})

    page.on("request", on_request)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        if scenario == "accept_all":
            clicked = await _click_button(page, vendor, _ACCEPT_SELECTORS, _ACCEPT_TEXT_PATTERNS)
            action_taken = "clicked_accept_all" if clicked else "no_accept_button_found"

        elif scenario == "reject_all":
            clicked = await _click_button(page, vendor, _REJECT_SELECTORS, _REJECT_TEXT_PATTERNS)
            action_taken = "clicked_reject_all" if clicked else "no_reject_button_found"

        elif scenario == "analytics_only":
            # Try to open preferences / settings panel
            action_taken = "attempted_partial"
            pref_patterns = re.compile(r"manage|preferences|settings|customis|customiz", re.I)
            try:
                btn = page.get_by_role("button").filter(has_text=pref_patterns).first
                if await btn.is_visible(timeout=3000):
                    await btn.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                    # Try to uncheck marketing, leave analytics
                    marketing_toggles = await page.locator(
                        "[data-category*='marketing'],[data-category*='advertising'],[id*='marketing']"
                    ).all()
                    for toggle in marketing_toggles:
                        try:
                            if await toggle.is_checked():
                                await toggle.uncheck()
                        except Exception:
                            pass
                    # Confirm/save
                    save_btn = page.get_by_role("button").filter(
                        has_text=re.compile(r"confirm|save|apply", re.I)
                    ).first
                    if await save_btn.is_visible(timeout=2000):
                        await save_btn.click(timeout=3000)
                        action_taken = "clicked_analytics_only"
            except Exception:
                action_taken = "partial_selection_failed"

        elif scenario == "close_without_choosing":
            # Try X / close button without explicit consent choice
            try:
                close_btn = page.get_by_role("button").filter(has_text=_CLOSE_PATTERNS).first
                if await close_btn.is_visible(timeout=3000):
                    await close_btn.click(timeout=3000)
                    action_taken = "clicked_close"
                else:
                    # Click outside the banner (top-left area)
                    await page.mouse.click(10, 10)
                    action_taken = "clicked_outside"
            except Exception:
                action_taken = "could_not_dismiss"

        await page.wait_for_timeout(2000)

        # Collect state after action
        raw_cookies = await context.cookies()
        cookies_after = [
            {"name": c["name"], "domain": c["domain"], "path": c["path"]}
            for c in raw_cookies
        ]

        # Consent mode update calls
        calls = await page.evaluate("() => window._consentModeCalls || []")
        for call in calls:
            if call.get("source") == "gtag":
                args = call.get("args", [])
                if len(args) >= 3 and args[0] == "consent" and args[1] == "update":
                    consent_mode_update = args[2] if isinstance(args[2], dict) else {}

    except Exception as exc:
        violations.append(f"ERROR: Scenario '{scenario}' failed: {exc}")

    finally:
        await browser.close()

    # Categorise requests fired
    analytics_fired = [r["url"] for r in network_requests if r["category"] == "analytics"]
    ads_fired = [r["url"] for r in network_requests if r["category"] == "ads"]

    # Violation detection
    if scenario == "reject_all":
        if analytics_fired:
            violations.append(
                "CRITICAL: Analytics tracking fired after user rejected consent"
            )
        if ads_fired:
            violations.append(
                "CRITICAL: Marketing/ads tracking fired after rejection"
            )
        if action_taken == "no_reject_button_found":
            violations.append(
                "HIGH: Reject All button not found at banner level — may require extra clicks (GDPR violation)"
            )

    if scenario == "close_without_choosing":
        if analytics_fired:
            violations.append(
                "CRITICAL: Tracking fires when banner is closed without explicit choice"
            )
        if ads_fired:
            violations.append(
                "HIGH: Ads tracking fires when banner dismissed without consent"
            )

    if consent_mode_update:
        for ct, state in consent_mode_update.items():
            if state == "granted" and scenario == "reject_all":
                violations.append(
                    f"CRITICAL: Consent Mode '{ct}' set to 'granted' after Reject All"
                )

    return {
        "scenario_name": scenario,
        "action_taken": action_taken,
        "cookies_after": cookies_after,
        "analytics_requests_fired": analytics_fired,
        "ads_requests_fired": ads_fired,
        "consent_mode_update": consent_mode_update,
        "violations": violations,
    }


async def _async_run_consent_scenarios(url: str, cmp_vendor: str) -> dict:
    from playwright.async_api import async_playwright

    scenarios_results = []
    all_violations = []

    async with async_playwright() as p:
        for scenario in ["accept_all", "reject_all", "analytics_only", "close_without_choosing"]:
            result = await _run_scenario(p, url, cmp_vendor, scenario)
            scenarios_results.append(result)
            all_violations.extend(result.get("violations", []))

    return {
        "scenarios": scenarios_results,
        "all_violations": all_violations,
    }


def run_consent_scenarios(url: str, cmp_vendor: str) -> dict:
    """
    Runs 4 consent scenarios and records network traffic + cookie state after each.

    SCENARIO 1 — Accept All
    SCENARIO 2 — Reject All
    SCENARIO 3 — Accept Analytics Only (if granular options exist)
    SCENARIO 4 — Close Banner Without Choosing

    Args:
        url: Website URL
        cmp_vendor: Detected CMP name (guides button selectors)

    Returns:
        dict with scenarios (list of scenario results), each containing:
            scenario_name, action_taken, cookies_after (list),
            analytics_requests_fired (list), ads_requests_fired (list),
            consent_mode_update (dict), violations (list of strings)
    """
    result = _run_async(_async_run_consent_scenarios(url, cmp_vendor))
    from consent_auditor import shared_state
    shared_state.set("scenarios", result)
    return result


# ---------------------------------------------------------------------------
# Tool 6: check_cookie_policy_page
# ---------------------------------------------------------------------------

async def _async_check_cookie_policy_page(base_url: str) -> dict:
    from playwright.async_api import async_playwright

    policy_found = False
    policy_url = ""
    categories_listed = False
    last_updated = ""
    dpo_contact_present = False
    error = None

    common_paths = [
        "/cookie-policy", "/cookie_policy", "/cookies",
        "/privacy-policy", "/privacy", "/privacy_policy",
        "/legal/cookies", "/legal/privacy",
        "/data-protection", "/gdpr",
    ]

    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

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
            )
            page = await context.new_page()

            # First try to find the link from the homepage/footer
            try:
                await page.goto(base_url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)
                links = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => ({href: e.href, text: e.innerText}))"
                )
                for link in links:
                    href = link.get("href", "").lower()
                    text = link.get("text", "").lower()
                    if any(kw in href or kw in text for kw in [
                        "cookie", "privacy", "datenschutz", "confidentialit"
                    ]):
                        policy_url = link["href"]
                        policy_found = True
                        break
            except Exception:
                pass

            # Fall back to common paths
            if not policy_found:
                for path in common_paths:
                    candidate = base + path
                    try:
                        resp = await page.goto(candidate, wait_until="domcontentloaded", timeout=10000)
                        if resp and resp.status == 200:
                            policy_url = candidate
                            policy_found = True
                            break
                    except Exception:
                        continue

            # Analyse policy page content
            if policy_found and policy_url:
                try:
                    await page.goto(policy_url, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(1500)
                    html = (await page.content()).lower()

                    category_hints = [
                        "analytics", "marketing", "functional", "necessary",
                        "essential", "performance", "advertising",
                    ]
                    categories_listed = sum(1 for h in category_hints if h in html) >= 2

                    # Last updated date pattern
                    date_match = re.search(
                        r"(last\s+updated|updated\s+on|effective\s+date)[:\s]+([a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
                        html, re.I
                    )
                    if date_match:
                        last_updated = date_match.group(2).strip()

                    dpo_hints = [
                        "data protection officer", "dpo", "dpo@", "privacy@",
                        "contact us", "gdpr@", "compliance@",
                    ]
                    dpo_contact_present = any(h in html for h in dpo_hints)

                except Exception:
                    pass

            await browser.close()

    except Exception as exc:
        error = str(exc)

    return {
        "policy_found": policy_found,
        "policy_url": policy_url,
        "categories_listed": categories_listed,
        "last_updated": last_updated,
        "dpo_contact_present": dpo_contact_present,
        "error": error,
    }


def check_cookie_policy_page(base_url: str) -> dict:
    """
    Tries to find and validate a Cookie Policy / Privacy Policy page.
    Checks for: cookie policy link in footer/banner,
                mentions of cookie categories, last updated date,
                contact/DPO information present.

    Args:
        base_url: Homepage URL

    Returns:
        dict with: policy_found (bool), policy_url (str),
                   categories_listed (bool), last_updated (str),
                   dpo_contact_present (bool)
    """
    result = _run_async(_async_check_cookie_policy_page(base_url))
    from consent_auditor import shared_state
    shared_state.set("cookie_policy", result)
    return result
