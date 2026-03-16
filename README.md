# 🔍 GDPR Consent Auditor

> An autonomous AI agent that crawls any website, tests its consent banner behaviour across multiple user scenarios, and generates a professional HTML compliance report — all with a single URL prompt.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Supported CMP Vendors](#supported-cmp-vendors)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Agent](#running-the-agent)
- [How to Use](#how-to-use)
- [Understanding the Report](#understanding-the-report)
- [Compliance Score](#compliance-score)
- [Violation Reference](#violation-reference)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Legal Disclaimer](#legal-disclaimer)

---

## Overview

The **GDPR Consent Auditor** is a multi-agent application built on [Google ADK](https://google.github.io/adk-docs/) that automatically audits websites for GDPR and ePrivacy Directive compliance. It launches a real Chromium browser, interacts with consent banners the same way a real user would, and checks for violations such as:

- Tracking cookies set **before** the user gives consent
- Missing or inaccessible **"Reject All"** option
- Analytics firing after the user **rejects** consent
- Missing or incomplete **Google Consent Mode v2** implementation
- Non-existent or inadequate **cookie/privacy policy** page

The result is a scored **self-contained HTML report** saved locally — no external hosting, no third-party dependencies.

---

## Architecture

The agent uses a **3-stage sequential pipeline**. Each stage is an independent LLM sub-agent that hands off results to the next:

```
User prompt: "Audit https://example.com"
        │
        ▼
┌───────────────────┐
│  crawler_agent    │  Stage 1 — Data Collection
│  (gemini-2.0)     │
│                   │  • crawl_website()
│                   │  • extract_consent_mode_signals()
│                   │  • check_cookie_policy_page()
└────────┬──────────┘
         │  crawl_results (session state)
         ▼
┌───────────────────┐
│ analyst_agent     │  Stage 2 — Analysis & Scenario Testing
│ (gemini-2.0)      │
│                   │  • detect_cmp_and_banner()
│                   │  • run_consent_scenarios()  ← 4 scenarios
└────────┬──────────┘
         │  analysis_results (session state)
         ▼
┌───────────────────┐
│ reporter_agent    │  Stage 3 — Report Generation
│ (gemini-2.0)      │
│                   │  • generate_gdpr_report()
└────────┬──────────┘
         │
         ▼
  📄 gdpr_report_example_com_20260314.html
```

---

## Features

| Feature | Details |
|---|---|
| **Real browser** | Headless Chromium via Playwright — no fake HTTP requests |
| **CMP detection** | Identifies 9 major vendors + custom implementations |
| **4 consent scenarios** | Accept All, Reject All, Partial (Analytics Only), Close Without Choosing |
| **Cookie inventory** | Lists all cookies set before any user action with tracking flag |
| **Google Consent Mode v2** | Reads `gtag('consent','default',…)` dataLayer signals |
| **IAB TCF detection** | Checks for `window.__tcfapi` presence |
| **Cookie policy audit** | Locates privacy page, checks categories, DPO contact, last updated |
| **Violation scoring** | CRITICAL / HIGH / MEDIUM / LOW weighted scoring (0–100) |
| **HTML report** | Self-contained, no CDN, inline CSS, printable |
| **Recommendations** | Prioritised fix list generated from violations |
| **Multilingual banners** | German, French dismiss/reject keywords supported |

---

## Supported CMP Vendors

The agent auto-detects the following Consent Management Platforms:

| Vendor | Detection Method |
|---|---|
| **OneTrust** | `onetrust` / `optanon` in HTML |
| **Cookiebot** | `cookiebot.com` in network requests |
| **TrustArc** | `trustarc.com` / `truste.com` requests |
| **Usercentrics** | `usercentrics` in HTML / requests |
| **Didomi** | `didomi` in HTML / requests |
| **Axeptio** | `axeptio` in HTML / requests |
| **CookieYes** | `cookieyes` in HTML |
| **Quantcast** | `__cmp` + `quantcast` in requests |
| **Custom** | Cookie + consent + banner keywords in HTML |

---

## Prerequisites

Before you begin, make sure you have:

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
- **pip** — comes with Python
- **Google Gemini API key** — get one free at [aistudio.google.com](https://aistudio.google.com/app/apikey)
- **Git** (optional, for cloning)

Check your Python version:
```bash
python --version   # must be 3.10 or higher
```

---

## Installation

Follow these steps in order. Each step must complete successfully before moving to the next.

### Step 1 — Navigate to the project folder

```bash
cd C:\dev\consent-agent\gdpr_consent_agent
```

> **Windows tip:** use the Command Prompt or PowerShell. Git Bash also works.

---

### Step 2 — Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

```bash
# Windows — Command Prompt
.venv\Scripts\activate.bat

# Windows — PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

You should see `(.venv)` at the start of your prompt.

---

### Step 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

Expected packages installed:
- `google-adk` — ADK agent framework
- `playwright` — browser automation
- `python-dotenv` — loads `.env` file
- `Jinja2` — HTML report templating

---

### Step 4 — Install the Chromium browser

```bash
playwright install chromium
```

This downloads a ~150 MB Chromium binary used for headless browsing.

---

### Step 5 — Set up your API key

Copy the environment template:

```bash
# Windows
copy consent_auditor\.env.example consent_auditor\.env

# macOS / Linux
cp consent_auditor/.env.example consent_auditor/.env
```

Open `consent_auditor/.env` in any text editor and replace the placeholder:

```env
GOOGLE_API_KEY=AIzaSy...your_real_key_here
```

> **Security:** Never commit `.env` to Git. It is already in `.gitignore` if you cloned this repo.

---

## Configuration

The `.env` file is the only configuration file you need to touch for basic use.

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | ✅ Yes | Gemini API key from Google AI Studio |

All other settings (model name, timeouts, scoring weights) are in the source files and can be edited directly if needed:

| Setting | File | Variable / location |
|---|---|---|
| Gemini model | `consent_auditor/agent.py` | `model="gemini-2.5-flash"` on each agent |
| Page load timeout | `tools/browser_tools.py` | `timeout=30000` (ms) in `_async_crawl_website` |
| CMP wait time | `tools/browser_tools.py` | `wait_for_timeout(4000)` |
| Violation weights | `tools/report_tools.py` | `calculate_compliance_score()` |
| Tracking domains | `tools/consent_tools.py` | `TRACKING_DOMAINS` list |

---

## Running the Agent

Start the ADK web interface:

```bash
# Make sure your virtual environment is active and you are in gdpr_consent_agent/
adk web
```

You should see output like:

```
INFO:     Started server process [12345]
INFO:     Uvicorn running on http://localhost:8000
```

Open your browser and go to:

```
http://localhost:8000
```

Select **gdpr_consent_auditor** from the agent dropdown on the left.

---

## How to Use

### Basic audit

In the chat input box, type:

```
Audit https://example.com
```

Replace `https://example.com` with the real URL you want to check. Always include `https://`.

---

### What happens next (step by step)

The agent will work through 3 stages automatically. You will see progress messages in the chat:

**Stage 1 — Crawler** *(~30–60 seconds)*
```
Crawl complete. Found: OneTrust, 12 cookies before consent,
Consent Mode: detected, Cookie Policy: found
```

**Stage 2 — Analyst** *(~90–120 seconds)*
```
Analysis complete. CMP: OneTrust.
Violations: 1 critical, 2 high, 1 medium, 0 low
```

**Stage 3 — Reporter** *(~5 seconds)*
```
Report saved: gdpr_report_example_com_20260314.html
Compliance Score: 57 / 100 — Significant Issues
Top violations:
  • CRITICAL: 3 tracking cookies set before user gave consent
  • HIGH: Google Consent Mode not implemented
  • HIGH: Reject All button not found at banner level
```

---

### Opening the report

The HTML report is saved in your **current working directory** (where you ran `adk web`):

```
C:\dev\consent-agent\gdpr_consent_agent\gdpr_report_example_com_20260314.html
```

Open it in any browser — it is fully self-contained with no external dependencies.

---

### Auditing multiple websites

Start a **new chat session** in the ADK web UI for each website (click the `+` or `New session` button), then send a new `Audit https://…` message. Each session maintains its own isolated state.

---

### Example prompts

```
Audit https://bbc.com
```
```
Audit https://shop.nike.com
```
```
Audit https://mycompany.eu/landing-page
```

> **Tip:** You can audit subpages — e.g. `/blog/article-1` — not just homepages. The agent crawls exactly the URL you provide.

---

## Understanding the Report

The generated HTML report is divided into sections:

### Compliance Score Circle
A 0–100 score prominently displayed at the top. See [Compliance Score](#compliance-score) for the scale.

### Summary Cards
Six at-a-glance KPIs:
- **CMP Vendor** — which CMP was detected
- **Consent Mode** — v1 / v2 / none
- **Violations** — total count (red if > 0)
- **Scenarios Passed** — X out of 4
- **Cookie Policy** — Found / Not Found
- **Reject All Available** — Yes / No

### CMP Detection
Full breakdown of the banner structure: vendor, visibility, type (modal/bar), whether it blocks the page, consent categories shown, and IAB TCF API presence.

### Google Consent Mode v2 Signals
Default state per consent type (`analytics_storage`, `ad_storage`, `ad_user_data`, `ad_personalization`, etc.) — all must be `denied` for GDPR compliance.

### Cookie Inventory (Before Consent)
Every cookie set the moment the page loads — before any user interaction. Cookies from known tracking domains are flagged in red.

### Consent Scenario Results
Four cards showing what happened during each scenario:
- How many analytics and ads requests fired
- How many cookies were set after the action
- Whether violations were detected

### Violations
Every violation listed with severity badge and description.

### Cookie / Privacy Policy
Status of the policy page: found URL, category coverage, last-updated date, DPO contact.

### Recommendations
Prioritised action list with effort estimates — ordered from most to least critical.

---

## Compliance Score

| Score | Status | Meaning |
|---|---|---|
| **90 – 100** | ✅ Compliant | No material issues |
| **70 – 89** | 🟡 Minor Issues | Small fixes needed |
| **50 – 69** | 🟠 Significant Issues | Multiple violations requiring attention |
| **0 – 49** | 🔴 Non-Compliant | Serious GDPR risk, immediate action required |

### Score deductions per violation

| Severity | Deduction | Examples |
|---|---|---|
| **CRITICAL** | −25 pts | Tracking before consent, tracking after rejection |
| **HIGH** | −15 pts | No Consent Mode v2, no Reject All, Consent Mode defaulting to `granted` |
| **MEDIUM** | −8 pts | Missing cookie policy, no DPO contact, incomplete categories |
| **LOW** | −3 pts | Minor documentation gaps |

---

## Violation Reference

| Code | Severity | Description |
|---|---|---|
| Tracking cookies set before consent | CRITICAL | Cookies from known trackers found before any user action |
| Analytics fired after Reject All | CRITICAL | GA / analytics requests observed post-rejection |
| Marketing/ads fired after rejection | CRITICAL | Ad network requests observed post-rejection |
| Tracking fires on banner dismiss | CRITICAL | Closing banner without choosing triggers tracking |
| Reject All not found at banner level | HIGH | User must navigate sub-menus to reject — GDPR violation |
| Consent Mode not implemented | HIGH | No `gtag('consent','default',…)` found |
| Consent Mode v1 detected | HIGH | Must upgrade to v2 (required since March 2024) |
| Consent Mode defaults to `granted` | HIGH | Any consent type defaulting to `granted` before user choice |
| No cookie/privacy policy page | MEDIUM | Required under GDPR and ePrivacy Directive |
| Cookie categories not listed | MEDIUM | Policy page does not describe cookie types |
| No DPO / controller contact | MEDIUM | Required under GDPR Article 13 |

---

## Project Structure

```
gdpr_consent_agent/
│
├── requirements.txt                  ← Python dependencies
│
└── consent_auditor/
    ├── __init__.py                   ← Exposes root_agent to ADK
    ├── agent.py                      ← All 3 sub-agents + SequentialAgent root
    ├── shared_state.py               ← In-memory state store
    ├── .env.example                  ← API key template (copy → .env)
    │
    └── tools/
        ├── __init__.py
        ├── browser_tools.py          ← crawl_website, take_scenario_screenshot
        ├── consent_tools.py          ← detect_cmp_and_banner,
        │                                extract_consent_mode_signals,
        │                                run_consent_scenarios,
        │                                check_cookie_policy_page
        └── report_tools.py           ← generate_gdpr_report (Jinja2 HTML)
```

### Tool responsibilities

| Tool | File | What it does |
|---|---|---|
| `crawl_website` | `browser_tools.py` | Launches Chromium, captures network requests, cookies, HTML, screenshot |
| `take_scenario_screenshot` | `browser_tools.py` | Takes a labelled screenshot for a given scenario |
| `detect_cmp_and_banner` | `consent_tools.py` | HTML/network fingerprinting to identify CMP vendor and banner structure |
| `extract_consent_mode_signals` | `consent_tools.py` | Reads Google Consent Mode v2 dataLayer defaults |
| `run_consent_scenarios` | `consent_tools.py` | Runs 4 interactive scenarios and records resulting traffic + cookies |
| `check_cookie_policy_page` | `consent_tools.py` | Finds and validates the cookie/privacy policy page |
| `generate_gdpr_report` | `report_tools.py` | Scores violations and renders self-contained HTML report |

---

## Troubleshooting

### `adk: command not found`
The ADK CLI is not on your PATH. Make sure your virtual environment is **activated** (`(.venv)` in the prompt), then try again.

---

### `GOOGLE_API_KEY not set` or `401 Unauthorized`
- Confirm `consent_auditor/.env` exists (not just `.env.example`)
- Confirm the key starts with `AIza…` and has no extra spaces or quotes
- Make sure the key has Gemini API access enabled in [Google AI Studio](https://aistudio.google.com/)

---

### `playwright install` fails or browser not found
Run the install again from your **activated virtual environment**:
```bash
python -m playwright install chromium
```
On Windows, you may also need system dependencies:
```bash
python -m playwright install-deps chromium
```

---

### The agent times out on a website
Some sites take longer to load or have aggressive bot protection. You can increase timeouts in `tools/browser_tools.py`:
```python
await page.goto(url, wait_until="domcontentloaded", timeout=60000)  # 60s
await page.wait_for_timeout(6000)                                    # 6s CMP wait
```

---

### `ModuleNotFoundError: No module named 'consent_auditor'`
Make sure you are running `adk web` from **inside the `gdpr_consent_agent/` directory**, not from the repo root.

---

### Report shows 0 cookies / no violations on a known bad site
Some CMPs load asynchronously. Try increasing the post-load wait in `browser_tools.py`:
```python
await page.wait_for_timeout(6000)   # was 4000
```

---

## Legal Disclaimer

> This tool is provided for **informational and educational purposes only**. The audit results do not constitute legal advice. GDPR compliance is a complex legal matter — consult a qualified Data Protection Officer or privacy lawyer before drawing compliance conclusions from this report. The authors accept no liability for actions taken based on the output of this tool.

---

*Built with [Google ADK](https://google.github.io/adk-docs/) · [Playwright](https://playwright.dev/) · [Jinja2](https://jinja.palletsprojects.com/) · [Gemini 2.0 Flash](https://deepmind.google/technologies/gemini/)*
