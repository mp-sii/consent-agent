"""Report generation tool — produces a self-contained HTML compliance report."""

import os
from datetime import datetime
from jinja2 import Template

# ---------------------------------------------------------------------------
# Compliance score
# ---------------------------------------------------------------------------

def calculate_compliance_score(violations: list) -> int:
    score = 100
    for v in violations:
        if "CRITICAL" in v:
            score -= 25
        elif "HIGH" in v:
            score -= 15
        elif "MEDIUM" in v:
            score -= 8
        elif "LOW" in v:
            score -= 3
    return max(0, score)


def _score_label(score: int) -> tuple:
    """Return (label, colour) for a given compliance score."""
    if score >= 90:
        return "Compliant", "#2E7D32"
    elif score >= 70:
        return "Minor Issues", "#F9A825"
    elif score >= 50:
        return "Significant Issues", "#E65100"
    else:
        return "Non-Compliant", "#B71C1C"


def _severity_colour(violation: str) -> str:
    if "CRITICAL" in violation:
        return "#C00000"
    elif "HIGH" in violation:
        return "#ED7D31"
    elif "MEDIUM" in violation:
        return "#2E75B6"
    return "#70AD47"


def _severity_bg(violation: str) -> str:
    if "CRITICAL" in violation:
        return "#FFE0E0"
    elif "HIGH" in violation:
        return "#FFF2CC"
    elif "MEDIUM" in violation:
        return "#D6E4F0"
    return "#E2EFDA"


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GDPR Consent Audit — {{ url }}</title>
<style>
  :root {
    --critical: #C00000; --critical-bg: #FFE0E0;
    --high: #ED7D31;     --high-bg: #FFF2CC;
    --medium: #2E75B6;   --medium-bg: #D6E4F0;
    --low: #70AD47;      --low-bg: #E2EFDA;
    --brand: #1F3864;    --brand-light: #2E4A8A;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #F5F7FA; color: #333; font-size: 14px; }
  header { background: var(--brand); color: #fff; padding: 24px 32px; }
  header h1 { font-size: 22px; font-weight: 700; }
  header p  { font-size: 13px; opacity: .75; margin-top: 4px; }
  .container { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }

  /* Score gauge */
  .score-section { text-align: center; margin: 24px 0; }
  .score-circle {
    width: 140px; height: 140px; border-radius: 50%; display: inline-flex;
    flex-direction: column; align-items: center; justify-content: center;
    border: 8px solid {{ score_colour }};
    background: #fff; box-shadow: 0 2px 12px rgba(0,0,0,.12);
  }
  .score-number { font-size: 42px; font-weight: 800; color: {{ score_colour }}; line-height: 1; }
  .score-label-text { font-size: 12px; color: #666; margin-top: 4px; }
  .score-status { font-size: 16px; font-weight: 600; color: {{ score_colour }}; margin-top: 8px; }

  /* Summary cards */
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 24px 0; }
  .card { background: #fff; border-radius: 8px; padding: 16px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  .card-title { font-size: 11px; text-transform: uppercase; letter-spacing: .6px; color: #888; }
  .card-value { font-size: 20px; font-weight: 700; color: var(--brand); margin-top: 4px; }

  /* Section headings */
  h2 { font-size: 17px; color: var(--brand); margin: 32px 0 12px; border-bottom: 2px solid #E0E6EF; padding-bottom: 6px; }
  h3 { font-size: 14px; color: #444; margin: 16px 0 8px; }

  /* Tables */
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 6px; overflow: hidden;
          box-shadow: 0 1px 4px rgba(0,0,0,.07); }
  th { background: var(--brand); color: #fff; padding: 10px 12px; text-align: left; font-size: 12px;
       text-transform: uppercase; letter-spacing: .5px; }
  td { padding: 9px 12px; border-bottom: 1px solid #EEF0F5; font-size: 13px; }
  tr:last-child td { border-bottom: none; }
  tr:nth-child(even) td { background: #F9FAFC; }

  /* Violations */
  .violation { border-left: 4px solid; padding: 10px 14px; margin: 8px 0;
               border-radius: 0 6px 6px 0; }
  .badge { display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px;
           border-radius: 12px; text-transform: uppercase; margin-right: 8px; color: #fff; }

  /* Scenarios */
  .scenarios { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
  .scenario-card { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  .scenario-name { font-weight: 700; font-size: 13px; color: var(--brand); margin-bottom: 8px; }
  .pass { color: #2E7D32; font-weight: 600; }
  .fail { color: #C00000; font-weight: 600; }
  .warn { color: #E65100; font-weight: 600; }

  /* Recommendations */
  .rec-item { background: #fff; border-radius: 6px; padding: 14px 18px; margin: 8px 0;
              box-shadow: 0 1px 3px rgba(0,0,0,.07); display: flex; gap: 14px; align-items: flex-start; }
  .rec-num { background: var(--brand); color: #fff; border-radius: 50%; width: 26px; height: 26px;
             display: flex; align-items: center; justify-content: center; font-weight: 700;
             font-size: 13px; flex-shrink: 0; }
  .rec-text { flex: 1; }
  .rec-meta { font-size: 11px; color: #888; margin-top: 4px; }

  /* Screenshots */
  .screenshots { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
  .screenshot-card { background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  .screenshot-card img { width: 100%; display: block; }
  .screenshot-caption { padding: 8px 12px; font-size: 12px; color: #555; background: #F9FAFC; }

  footer { text-align: center; font-size: 11px; color: #aaa; padding: 32px 16px;
           border-top: 1px solid #E0E6EF; margin-top: 40px; }

  .pill { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
  .pill-green { background: #E8F5E9; color: #2E7D32; }
  .pill-red   { background: #FFEBEE; color: #C62828; }
  .pill-gray  { background: #EEEEEE; color: #555; }
</style>
</head>
<body>

<header>
  <h1>GDPR Consent Compliance Audit</h1>
  <p>{{ url }} &nbsp;|&nbsp; Generated {{ generated_at }}</p>
</header>

<div class="container">

  <!-- Compliance Score -->
  <div class="score-section">
    <div class="score-circle">
      <div class="score-number">{{ compliance_score }}</div>
      <div class="score-label-text">/ 100</div>
    </div>
    <div class="score-status">{{ score_status }}</div>
  </div>

  <!-- Summary Cards -->
  <div class="cards">
    <div class="card">
      <div class="card-title">CMP Vendor</div>
      <div class="card-value">{{ cmp_vendor }}</div>
    </div>
    <div class="card">
      <div class="card-title">Consent Mode</div>
      <div class="card-value">{{ consent_mode_version }}</div>
    </div>
    <div class="card">
      <div class="card-title">Violations</div>
      <div class="card-value" style="color: {% if total_violations > 0 %}#C00000{% else %}#2E7D32{% endif %}">
        {{ total_violations }}
      </div>
    </div>
    <div class="card">
      <div class="card-title">Scenarios Passed</div>
      <div class="card-value">{{ scenarios_passed }} / {{ total_scenarios }}</div>
    </div>
    <div class="card">
      <div class="card-title">Cookie Policy</div>
      <div class="card-value" style="font-size:14px">
        {% if policy_found %}<span class="pill pill-green">Found</span>{% else %}<span class="pill pill-red">Not Found</span>{% endif %}
      </div>
    </div>
    <div class="card">
      <div class="card-title">Reject All Available</div>
      <div class="card-value" style="font-size:14px">
        {% if reject_all_available %}<span class="pill pill-green">Yes</span>{% else %}<span class="pill pill-red">No</span>{% endif %}
      </div>
    </div>
  </div>

  <!-- CMP Detection -->
  <h2>CMP Detection</h2>
  <table>
    <tr><th>Property</th><th>Value</th></tr>
    <tr><td>CMP Vendor</td><td>{{ cmp_vendor }}</td></tr>
    <tr><td>CMP Detected</td><td>{% if cmp_detected %}<span class="pill pill-green">Yes</span>{% else %}<span class="pill pill-red">No</span>{% endif %}</td></tr>
    <tr><td>Banner Visible</td><td>{% if banner_visible %}Yes{% else %}No{% endif %}</td></tr>
    <tr><td>Banner Type</td><td>{{ banner_type }}</td></tr>
    <tr><td>Blocks Page Interaction</td><td>{% if blocks_interaction %}Yes{% else %}No{% endif %}</td></tr>
    <tr><td>Consent Categories</td><td>{{ consent_categories | join(', ') if consent_categories else '—' }}</td></tr>
    <tr><td>Reject All at Top Level</td><td>{% if reject_all_available %}<span class="pill pill-green">Yes</span>{% else %}<span class="pill pill-red">No</span>{% endif %}</td></tr>
    <tr><td>IAB TCF API Present</td><td>{% if has_tcf_api %}Yes{% else %}No{% endif %}</td></tr>
  </table>

  <!-- Google Consent Mode -->
  <h2>Google Consent Mode v2 Signals</h2>
  <table>
    <tr><th>Property</th><th>Value</th></tr>
    <tr><td>Consent Mode Detected</td><td>{% if consent_mode_detected %}<span class="pill pill-green">Yes</span>{% else %}<span class="pill pill-red">No</span>{% endif %}</td></tr>
    <tr><td>Version</td><td>{{ consent_mode_version }}</td></tr>
    <tr><td>All Denied by Default</td><td>{% if all_denied_by_default %}<span class="pill pill-green">Yes</span>{% else %}<span class="pill pill-red">No</span>{% endif %}</td></tr>
    <tr><td>Wait-for-Update</td><td>{% if has_wait_for_update %}{{ wait_for_update_ms }} ms{% else %}Not set{% endif %}</td></tr>
    <tr><td>GDPR Compliant</td><td>{% if gdpr_consent_mode_compliant %}<span class="pill pill-green">Yes</span>{% else %}<span class="pill pill-red">No</span>{% endif %}</td></tr>
  </table>

  {% if default_states %}
  <h3>Default State per Consent Type</h3>
  <table>
    <tr><th>Consent Type</th><th>Default State</th></tr>
    {% for ctype, state in default_states.items() %}
    <tr>
      <td>{{ ctype }}</td>
      <td>
        {% if state == 'denied' %}<span class="pill pill-green">denied</span>
        {% else %}<span class="pill pill-red">{{ state }}</span>{% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

  <!-- Cookie Inventory -->
  <h2>Cookie Inventory (Before Consent)</h2>
  {% if cookies_before_consent %}
  <table>
    <tr><th>Name</th><th>Domain</th><th>HttpOnly</th><th>Secure</th><th>Tracking?</th></tr>
    {% for c in cookies_before_consent %}
    <tr>
      <td>{{ c.name }}</td>
      <td>{{ c.domain }}</td>
      <td>{{ 'Yes' if c.httpOnly else 'No' }}</td>
      <td>{{ 'Yes' if c.secure else 'No' }}</td>
      <td>
        {% set is_tracker = false %}
        {% for td in tracking_domains %}{% if td in c.domain %}{% set is_tracker = true %}{% endif %}{% endfor %}
        {% if is_tracker %}<span class="pill pill-red">Yes</span>{% else %}No{% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p style="color:#888; font-style:italic">No cookies captured before consent.</p>
  {% endif %}

  <!-- Scenario Results -->
  <h2>Consent Scenario Results</h2>
  <div class="scenarios">
    {% for s in scenarios %}
    <div class="scenario-card">
      <div class="scenario-name">{{ s.scenario_name | replace('_', ' ') | title }}</div>
      <div>Action: <strong>{{ s.action_taken }}</strong></div>
      <div style="margin-top:6px">
        Analytics fired:
        {% if s.analytics_requests_fired %}
          <span class="fail">{{ s.analytics_requests_fired | length }} requests</span>
        {% else %}
          <span class="pass">None</span>
        {% endif %}
      </div>
      <div>
        Ads fired:
        {% if s.ads_requests_fired %}
          <span class="fail">{{ s.ads_requests_fired | length }} requests</span>
        {% else %}
          <span class="pass">None</span>
        {% endif %}
      </div>
      <div style="margin-top:6px">
        Cookies after: <strong>{{ s.cookies_after | length }}</strong>
      </div>
      {% if s.violations %}
      <div style="margin-top:8px; font-size:12px; color:#C00000">
        ⚠ {{ s.violations | length }} violation(s)
      </div>
      {% else %}
      <div style="margin-top:8px; font-size:12px; color:#2E7D32">✓ No violations</div>
      {% endif %}
    </div>
    {% endfor %}
  </div>

  <!-- Violations -->
  <h2>Violations ({{ all_violations | length }} total)</h2>
  {% if all_violations %}
    {% for v in all_violations %}
    <div class="violation" style="border-color: {{ v | violation_colour }}; background: {{ v | violation_bg }}">
      <span class="badge" style="background: {{ v | violation_colour }}">
        {% if 'CRITICAL' in v %}CRITICAL{% elif 'HIGH' in v %}HIGH{% elif 'MEDIUM' in v %}MEDIUM{% else %}LOW{% endif %}
      </span>
      {{ v | replace('CRITICAL: ', '') | replace('HIGH: ', '') | replace('MEDIUM: ', '') | replace('LOW: ', '') }}
    </div>
    {% endfor %}
  {% else %}
    <p style="color:#2E7D32; font-weight:600">No violations detected. ✓</p>
  {% endif %}

  <!-- Cookie Policy -->
  <h2>Cookie / Privacy Policy</h2>
  <table>
    <tr><th>Property</th><th>Value</th></tr>
    <tr><td>Policy Found</td><td>{% if policy_found %}<span class="pill pill-green">Yes</span>{% else %}<span class="pill pill-red">No</span>{% endif %}</td></tr>
    <tr><td>Policy URL</td><td>{% if policy_url %}<a href="{{ policy_url }}">{{ policy_url }}</a>{% else %}—{% endif %}</td></tr>
    <tr><td>Categories Listed</td><td>{% if categories_listed %}Yes{% else %}No{% endif %}</td></tr>
    <tr><td>Last Updated</td><td>{{ last_updated if last_updated else '—' }}</td></tr>
    <tr><td>DPO / Contact Present</td><td>{% if dpo_contact_present %}Yes{% else %}No{% endif %}</td></tr>
  </table>

  <!-- Recommendations -->
  <h2>Recommendations</h2>
  {% if recommendations %}
  {% for rec in recommendations %}
  <div class="rec-item">
    <div class="rec-num">{{ loop.index }}</div>
    <div class="rec-text">
      <strong>{{ rec.title }}</strong>
      <div>{{ rec.detail }}</div>
      <div class="rec-meta">Priority: {{ rec.priority }} &nbsp;|&nbsp; Effort: {{ rec.effort }}</div>
    </div>
  </div>
  {% endfor %}
  {% else %}
  <p style="color:#2E7D32">No recommendations — site is fully compliant!</p>
  {% endif %}

  <!-- Screenshots -->
  {% if screenshots %}
  <h2>Screenshots</h2>
  <div class="screenshots">
    {% for s in screenshots %}
    {% if s.screenshot_b64 %}
    <div class="screenshot-card">
      <img src="data:image/png;base64,{{ s.screenshot_b64 }}" alt="{{ s.scenario_name }}">
      <div class="screenshot-caption">{{ s.scenario_name | replace('_', ' ') | title }}</div>
    </div>
    {% endif %}
    {% endfor %}
  </div>
  {% endif %}

</div>

<footer>
  Generated by GDPR Consent Auditor &nbsp;|&nbsp; {{ generated_at }} &nbsp;|&nbsp;
  This report is for informational purposes only and does not constitute legal advice.
</footer>

</body>
</html>
"""


def _build_recommendations(audit_data: dict) -> list:
    recs = []
    violations = audit_data.get("all_violations", [])
    cmp = audit_data.get("cmp_detection", {})
    cm = audit_data.get("consent_mode", {})
    policy = audit_data.get("cookie_policy", {})

    if not cmp.get("cmp_detected"):
        recs.append({
            "title": "Implement a Consent Management Platform (CMP)",
            "detail": "No CMP detected. You must implement a GDPR-compliant CMP before collecting any user data.",
            "priority": "Critical",
            "effort": "High",
        })

    if not cmp.get("reject_all_available"):
        recs.append({
            "title": "Add 'Reject All' to the top-level consent banner",
            "detail": "GDPR requires reject to be as easy as accept. Move 'Reject All' to the first screen of the banner.",
            "priority": "High",
            "effort": "Low",
        })

    if cm.get("consent_mode_version") != "v2":
        recs.append({
            "title": "Upgrade to Google Consent Mode v2",
            "detail": "Consent Mode v2 is required for GA4 and Google Ads from March 2024 onwards.",
            "priority": "High",
            "effort": "Medium",
        })

    if cm.get("consent_mode_detected") and not cm.get("all_denied_by_default"):
        recs.append({
            "title": "Set all Consent Mode defaults to 'denied'",
            "detail": "All gtag('consent','default') values must be 'denied' until the user grants consent.",
            "priority": "High",
            "effort": "Low",
        })

    has_pre_consent = any(
        "before consent" in v.lower() or "before user" in v.lower()
        for v in violations
    )
    if has_pre_consent:
        recs.append({
            "title": "Stop firing tracking cookies before consent",
            "detail": "Tracking cookies must not be set until the user explicitly accepts. Review tag firing rules in your TMS.",
            "priority": "Critical",
            "effort": "Medium",
        })

    has_reject_fire = any("after rejection" in v.lower() or "after user rejected" in v.lower() for v in violations)
    if has_reject_fire:
        recs.append({
            "title": "Ensure tracking stops after 'Reject All'",
            "detail": "Analytics/ads tracking is still firing after the user rejects consent. Fix tag blocking logic.",
            "priority": "Critical",
            "effort": "Medium",
        })

    if not policy.get("policy_found"):
        recs.append({
            "title": "Create and publish a Cookie Policy page",
            "detail": "No cookie policy page found. A cookie policy is required under GDPR and ePrivacy Directive.",
            "priority": "High",
            "effort": "Medium",
        })

    if policy.get("policy_found") and not policy.get("dpo_contact_present"):
        recs.append({
            "title": "Add DPO / data controller contact details to the cookie policy",
            "detail": "GDPR Article 13 requires you to identify the controller and provide contact information.",
            "priority": "Medium",
            "effort": "Low",
        })

    return recs


# ---------------------------------------------------------------------------
# Tool 7: generate_gdpr_report
# ---------------------------------------------------------------------------

def generate_gdpr_report(output_dir: str = ".") -> str:
    """
    Generates a professional self-contained HTML GDPR compliance report and saves it to disk.
    All audit data (URL, cookies, CMP results, consent scenarios) is read automatically
    from shared state — no other arguments are needed.
    The output filename is derived automatically from the audited URL and today's date.

    Args:
        output_dir: Directory to save the report in (default: current working directory)

    Returns:
        Absolute path to the saved HTML report file
    """
    from consent_auditor import shared_state
    from urllib.parse import urlparse as _urlparse

    url = shared_state.get("url", "unknown")

    # Auto-build filename:  gdpr_report_www_example_com_20260316.html
    try:
        hostname = _urlparse(url).netloc.replace(".", "_").replace("-", "_")
    except Exception:
        hostname = "unknown"
    date_str = datetime.utcnow().strftime("%Y%m%d")
    output_filename = os.path.join(output_dir, f"gdpr_report_{hostname}_{date_str}.html")

    audit_data = {
        "url": url,
        "crawl": shared_state.get("crawl", {}),
        "consent_mode": shared_state.get("consent_mode", {}),
        "cookie_policy": shared_state.get("cookie_policy", {}),
        "cmp_detection": shared_state.get("cmp_detection", {}),
        "scenarios": shared_state.get("scenarios", {}),
    }

    # Extract sub-sections
    crawl = audit_data.get("crawl", {})
    cmp = audit_data.get("cmp_detection", {})
    cm = audit_data.get("consent_mode", {})
    scenarios_data = audit_data.get("scenarios", {})
    policy = audit_data.get("cookie_policy", {})
    screenshots = audit_data.get("screenshots", [])

    all_violations: list = []
    for s in scenarios_data.get("scenarios", []):
        all_violations.extend(s.get("violations", []))
    # Also include any top-level violations
    all_violations.extend(audit_data.get("extra_violations", []))

    # Check pre-consent tracking cookies violation
    pre_consent_trackers = [
        c for c in crawl.get("cookies_before_consent", [])
        if any(td in c.get("domain", "") for td in [
            "google-analytics.com", "doubleclick.net", "facebook.net",
            "googlesyndication.com", "segment.io", "hotjar.com",
        ])
    ]
    if pre_consent_trackers:
        all_violations.insert(0,
            f"CRITICAL: {len(pre_consent_trackers)} tracking cookie(s) set before user gave consent"
        )

    # Check Consent Mode defaults
    for ct, state in cm.get("default_states", {}).items():
        if state == "granted":
            all_violations.append(
                f"HIGH: Google Consent Mode defaults '{ct}' to 'granted' — must default to 'denied'"
            )

    if not policy.get("policy_found"):
        all_violations.append("MEDIUM: No cookie/privacy policy page found")
    if policy.get("policy_found") and not policy.get("categories_listed"):
        all_violations.append("MEDIUM: Cookie policy does not clearly list cookie categories")
    if policy.get("policy_found") and not policy.get("dpo_contact_present"):
        all_violations.append("MEDIUM: No DPO or data controller contact found in cookie policy")

    if cm.get("consent_mode_detected") and cm.get("consent_mode_version") == "v1":
        all_violations.append("HIGH: Google Consent Mode v1 detected — upgrade to v2 required")
    if not cm.get("consent_mode_detected"):
        all_violations.append("HIGH: Google Consent Mode not implemented")

    # Deduplicate
    seen = set()
    unique_violations = []
    for v in all_violations:
        if v not in seen:
            seen.add(v)
            unique_violations.append(v)
    all_violations = unique_violations

    compliance_score = calculate_compliance_score(all_violations)
    score_status, score_colour = _score_label(compliance_score)

    scenarios_list = scenarios_data.get("scenarios", [])
    scenarios_passed = sum(
        1 for s in scenarios_list if not s.get("violations")
    )

    recommendations = _build_recommendations({**audit_data, "all_violations": all_violations})

    # Jinja2 custom filters
    from jinja2 import Environment
    env = Environment()
    env.filters["violation_colour"] = _severity_colour
    env.filters["violation_bg"] = _severity_bg

    template = env.from_string(_REPORT_TEMPLATE)

    html = template.render(
        url=crawl.get("url", audit_data.get("url", "Unknown")),
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        compliance_score=compliance_score,
        score_status=score_status,
        score_colour=score_colour,
        # CMP
        cmp_vendor=cmp.get("cmp_vendor", "Unknown"),
        cmp_detected=cmp.get("cmp_detected", False),
        banner_visible=cmp.get("banner_visible", False),
        banner_type=cmp.get("banner_type", "unknown"),
        blocks_interaction=cmp.get("blocks_interaction", False),
        consent_categories=cmp.get("consent_categories", []),
        reject_all_available=cmp.get("reject_all_available", False),
        has_tcf_api=crawl.get("has_tcf_api", False),
        # Consent Mode
        consent_mode_detected=cm.get("consent_mode_detected", False),
        consent_mode_version=cm.get("consent_mode_version", "none"),
        default_states=cm.get("default_states", {}),
        all_denied_by_default=cm.get("all_denied_by_default", False),
        has_wait_for_update=cm.get("has_wait_for_update", False),
        wait_for_update_ms=cm.get("wait_for_update_ms", 0),
        gdpr_consent_mode_compliant=cm.get("gdpr_consent_mode_compliant", False),
        # Cookies
        cookies_before_consent=crawl.get("cookies_before_consent", []),
        tracking_domains=[
            "google-analytics.com", "doubleclick.net", "facebook.net",
            "googlesyndication.com", "segment.io", "hotjar.com",
            "clarity.ms", "mixpanel.com",
        ],
        # Scenarios
        scenarios=scenarios_list,
        scenarios_passed=scenarios_passed,
        total_scenarios=len(scenarios_list),
        # Violations
        all_violations=all_violations,
        total_violations=len(all_violations),
        # Policy
        policy_found=policy.get("policy_found", False),
        policy_url=policy.get("policy_url", ""),
        categories_listed=policy.get("categories_listed", False),
        last_updated=policy.get("last_updated", ""),
        dpo_contact_present=policy.get("dpo_contact_present", False),
        # Recommendations
        recommendations=recommendations,
        # Screenshots
        screenshots=screenshots,
    )

    output_path = os.path.abspath(output_filename)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
