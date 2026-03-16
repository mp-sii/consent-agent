"""GDPR Consent Auditor — three sub-agents orchestrated by a SequentialAgent."""

from google.adk.agents import Agent, SequentialAgent
from google.genai import types

from .tools.browser_tools import crawl_website, take_scenario_screenshot
from .tools.consent_tools import (
    detect_cmp_and_banner,
    extract_consent_mode_signals,
    run_consent_scenarios,
    check_cookie_policy_page,
)
from .tools.report_tools import generate_gdpr_report

# Shared retry config — retries up to 3 times with a 60 s initial back-off.
# This handles 429 RESOURCE_EXHAUSTED responses from the Gemini API.
_retry_config = types.GenerateContentConfig(
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(
            initial_delay=60.0,   # seconds — matches the ~44 s retry window
            attempts=3,
        ),
    ),
)

# ── Sub-Agent 1: Crawler ──────────────────────────────────────────────────────
crawler_agent = Agent(
    name="crawler_agent",
    model="gemini-2.5-flash",
    generate_content_config=_retry_config,
    description="Visits the website and captures raw technical data",
    instruction="""
You are a technical web crawler. Your only job is to gather raw data.

When given a URL:
1. Call crawl_website(url) to get initial page state, cookies, network requests, and HTML.
2. Call extract_consent_mode_signals(url) to get Google Consent Mode dataLayer signals.
3. Call check_cookie_policy_page(base_url) to locate the privacy/cookie policy.
4. Store all results — do NOT analyse yet, just collect.

Report back: "Crawl complete. Found: [CMP hint from HTML], [X] cookies before consent,
Consent Mode: [detected/not detected], Cookie Policy: [found/not found]"
""",
    tools=[crawl_website, extract_consent_mode_signals, check_cookie_policy_page],
    output_key="crawl_results",
)

# ── Sub-Agent 2: Consent Analyst ──────────────────────────────────────────────
analyst_agent = Agent(
    name="consent_analyst_agent",
    model="gemini-2.5-flash",
    generate_content_config=_retry_config,
    description="Detects CMP, runs consent scenarios, identifies GDPR violations",
    instruction="""
You are a GDPR consent specialist. You analyse raw crawl data and run active tests.

Using the crawl_results from session state:
1. Call detect_cmp_and_banner(page_html_snippet, network_requests) to identify the CMP
   vendor and banner structure. Pass the page_html_snippet and network_requests values
   from crawl_results.
2. Call run_consent_scenarios(url, cmp_vendor) to test all 4 user scenarios:
   - Accept All
   - Reject All
   - Accept partial (analytics only if possible)
   - Close without choosing
3. Compile ALL violations found across all scenarios into a single violations list.
4. Categorise each violation: CRITICAL / HIGH / MEDIUM / LOW

GDPR rules you must check:
- Tracking cookies MUST NOT fire before consent
- "Reject All" MUST be as easy to find as "Accept All" (no buried menus)
- Consent Mode v2 MUST default all types to 'denied'
- Closing the banner WITHOUT choosing MUST NOT trigger tracking
- Consent must be EXPLICIT — pre-ticked boxes = CRITICAL violation
- Cookie policy must be linked from the consent banner

Report: "Analysis complete. CMP: [vendor]. Violations: [N] critical, [N] high, [N] medium, [N] low"
""",
    tools=[detect_cmp_and_banner, run_consent_scenarios],
    output_key="analysis_results",
)

# ── Sub-Agent 3: Report Generator ─────────────────────────────────────────────
reporter_agent = Agent(
    name="report_generator_agent",
    model="gemini-2.5-flash",
    generate_content_config=_retry_config,
    description="Generates the final professional GDPR compliance HTML report",
    instruction="""
You are a report file writer. You have exactly one task: call generate_gdpr_report().

Call generate_gdpr_report with no arguments. The tool handles everything automatically.

After the tool call succeeds, reply with a short summary:
  - Report saved to: <file path returned by the tool>
  - Compliance score and status
  - Top violations found
""",
    tools=[generate_gdpr_report],
    output_key="report_results",
)

# ── Root Agent: SequentialAgent Orchestrator ──────────────────────────────────
root_agent = SequentialAgent(
    name="gdpr_consent_auditor",
    description=(
        "Full GDPR consent compliance audit for any website. "
        "Provide a URL to begin."
    ),
    sub_agents=[crawler_agent, analyst_agent, reporter_agent],
)
