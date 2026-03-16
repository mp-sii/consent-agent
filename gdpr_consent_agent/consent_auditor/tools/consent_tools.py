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
        page_html_snippet: HTML from the LLM (may be truncated to 10 KB)
        network_requests: Network requests from the LLM (may be capped at 50)

    Returns:
        dict with: cmp_vendor, cmp_detected (bool), banner_visible (bool),
                   banner_type, blocks_interaction (bool),
                   consent_categories (list), reject_all_available (bool),
                   gdpr_compliant_banner_structure (bool)
    """
    # Always prefer the FULL data from shared_state — the LLM only sees
    # truncated HTML (10 KB) and capped network requests (50 entries).
    from consent_auditor import shared_state as _ss
    crawl = _ss.get("crawl", {})
    html_lower = (crawl.get("page_html_snippet") or page_html_snippet or "").lower()
    all_requests = crawl.get("network_requests") or network_requests or []
    request_domains = " ".join(r.get("url", "") for r in all_requests).lower()

    cmp_vendor = "none"
    cmp_detected = False

    # CMP fingerprint detection
    if "onetrust" in html_lower or "optanon" in html_lower:
        cmp_vendor = "OneTrust"
        cmp_detected = True
    elif (
        "cookiebot" in request_domains
        or "cookiebot" in html_lower
        or "cookieconsent" in html_lower
        or "consent.cookiebot.com" in request_domains
    ):
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
    elif "consentmanager" in html_lower or "consentmanager" in request_domains:
        cmp_vendor = "Consentmanager"
        cmp_detected = True
    elif "iubenda" in html_lower or "iubenda" in request_domains:
        cmp_vendor = "Iubenda"
        cmp_detected = True
    elif "borlabs" in html_lower:
        cmp_vendor = "Borlabs Cookie"
        cmp_detected = True
    elif "cookiefirst" in html_lower or "cookiefirst" in request_domains:
        cmp_vendor = "CookieFirst"
        cmp_detected = True
    elif "complianz" in html_lower:
        cmp_vendor = "Complianz"
        cmp_detected = True
    elif "klaro" in html_lower and "consent" in html_lower:
        cmp_vendor = "Klaro"
        cmp_detected = True
    elif "termly" in html_lower or "termly" in request_domains:
        cmp_vendor = "Termly"
        cmp_detected = True
    elif "civic" in html_lower and "cookie" in html_lower and "control" in html_lower:
        cmp_vendor = "Civic UK Cookie Control"
        cmp_detected = True
    elif (
        "cookie" in html_lower
        and (
            "consent" in html_lower or "samtykke" in html_lower        # EN / NO
            or "consentement" in html_lower or "toestemming" in html_lower  # FR / NL
            or "consentimiento" in html_lower or "consenso" in html_lower   # ES / IT-PT
            or "zgoda" in html_lower or "souhlas" in html_lower             # PL / CS
            or "beleegyezés" in html_lower or "consimțământ" in html_lower  # HU / RO
            or "samtycke" in html_lower or "suostumus" in html_lower        # SV / FI
            or "souhlas" in html_lower or "privacyverklaring" in html_lower # CS / NL
        )
        and (
            "banner" in html_lower or "popup" in html_lower
            or "notice" in html_lower or "modal" in html_lower
            or "informasjonskapsler" in html_lower                          # NO
            or "hinweis" in html_lower or "meldung" in html_lower          # DE
            or "melding" in html_lower or "avis" in html_lower             # NL / FR
            or "powiadomienie" in html_lower or "oznámení" in html_lower   # PL / CS
            or "értesítés" in html_lower or "notificare" in html_lower     # HU / RO
            or "avviso" in html_lower or "ilmoitus" in html_lower          # IT / FI
        )
    ):
        cmp_vendor = "custom"
        cmp_detected = True

    # Banner visibility heuristics — all major European languages
    banner_keywords = [
        # ── English ──────────────────────────────────────────────────────────
        "cookie-banner", "cookie_banner", "cookiebanner",
        "consent-banner", "consent_banner",
        "cookie-notice", "cookie_notice",
        "cookie-popup", "gdpr-banner",
        "cc-banner", "cc-window",
        "consent-modal", "privacy-banner",
        # ── Norwegian (Bokmål / Nynorsk) ─────────────────────────────────────
        "informasjonskapsler",    # "cookies"
        "cookiemelding", "cookie-melding",
        "samtykke",               # "consent"
        "tillat alle cookies",    # "allow all cookies"
        "tillat utvalgt",         # "allow selected"
        "personvern",             # "privacy"
        # ── German ───────────────────────────────────────────────────────────
        "cookie-hinweis", "datenschutzhinweis", "datenschutz-banner",
        "zustimmung", "einwilligung",   # "consent" / "agreement"
        # ── French ───────────────────────────────────────────────────────────
        "bandeau-cookie", "bandeau cookie",
        "consentement", "gestion des cookies",
        # ── Dutch ────────────────────────────────────────────────────────────
        "cookiemelding",          # covers both NL and NO
        "cookievoorkeuren",       # "cookie preferences"
        "cookiebeleid",           # "cookie policy"
        "privacymelding",         # "privacy notice"
        "toestemming",            # "consent"
        # ── Spanish ──────────────────────────────────────────────────────────
        "aviso de cookies",
        "política de cookies",
        "consentimiento de cookies",
        "gestión de cookies",
        # ── Italian ──────────────────────────────────────────────────────────
        "informativa sui cookie",
        "consenso ai cookie",
        "preferenze cookie",
        "gestione dei cookie",
        # ── Polish ───────────────────────────────────────────────────────────
        "pliki cookie",
        "ciasteczka",
        "polityka cookie",
        "ustawienia cookies",
        # ── Portuguese ───────────────────────────────────────────────────────
        "política de cookies",    # shared with Spanish
        "consentimento de cookies",
        "aviso de cookies",       # shared with Spanish
        "preferências de cookies",
        # ── Swedish ──────────────────────────────────────────────────────────
        "cookiesamtycke",         # "cookie consent"
        "cookieinformation",
        "kakor",                  # "cookies" in Swedish
        "integritetspolicy",      # "privacy policy"
        # ── Danish ───────────────────────────────────────────────────────────
        "cookiepolitik",          # "cookie policy"
        "cookiesamtykke",         # "cookie consent"
        "privatlivspolitik",      # "privacy policy"
        # ── Finnish ──────────────────────────────────────────────────────────
        "evästeet",               # "cookies"
        "evästekäytäntö",         # "cookie policy"
        "evästeilmoitus",         # "cookie notice"
        "tietosuoja",             # "privacy"
        # ── Czech ────────────────────────────────────────────────────────────
        "soubory cookie",
        "nastavení cookies",
        "zásady cookies",
        # ── Slovak ───────────────────────────────────────────────────────────
        "súbory cookie",
        "zásady cookies",
        # ── Hungarian ────────────────────────────────────────────────────────
        "sütik",                  # "cookies"
        "süti-tájékoztató",       # "cookie notice"
        "cookie-kezelés",         # "cookie management"
        # ── Romanian ─────────────────────────────────────────────────────────
        "cookie-uri",             # "cookies"
        "politica de cookies",
        "consimțământ",           # "consent"
        # ── Croatian ─────────────────────────────────────────────────────────
        "kolačići",               # "cookies"
        "obavijest o kolačićima", # "cookie notice"
        # ── Slovenian ────────────────────────────────────────────────────────
        "piškotki",               # "cookies"
        "obvestilo o piškotkih",  # "cookie notice"
        # ── Estonian ─────────────────────────────────────────────────────────
        "küpsised",               # "cookies"
        "küpsiste teatis",        # "cookie notice"
        # ── Latvian ──────────────────────────────────────────────────────────
        "sīkdatnes",              # "cookies"
        "sīkdatņu paziņojums",    # "cookie notice"
        # ── Lithuanian ───────────────────────────────────────────────────────
        "slapukai",               # "cookies"
        "slapukų pranešimas",     # "cookie notice"
        # ── Bulgarian (Cyrillic) ─────────────────────────────────────────────
        "бисквитки",              # "cookies"
        "бисквитките",
        # ── Greek ────────────────────────────────────────────────────────────
        "πολιτική cookies",       # "cookie policy"
        "συναίνεση",              # "consent"
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

    # Consent categories — all major European languages
    # Each element is a regex; label = first alternative.title()
    category_patterns = [
        # Analytics / Statistics  (label → "Analytics")
        (
            r"analytics|statistik|statistic|statistikk"                   # EN / DE / NO
            r"|analitica|analytique|statistieken|estadísticas|estatísticas" # IT / FR / NL / ES / PT
            r"|statystyki|analytiikka|tilastot|statistiky|štatistiky"       # PL / FI / CS / SK
            r"|analitika|statisztikák|statistici|statistike|analyysi"       # HU / RO / HR-SL / FI
        ),
        # Marketing / Advertising  (label → "Marketing")
        (
            r"marketing|advertising|advertisement|markedsf[øo]ring"        # EN / NO
            r"|werbung|publicité|reclame|publicidad|pubblicità"             # DE / FR / NL / ES / IT
            r"|publicidade|marketingowe|marknadsföring|mainonta"            # PT / PL / SV / FI
            r"|reklamní|marketingové|hirdetési|publicitate"                 # CS / SK / HU / RO
            r"|marketinške|oglaševanje|reklāma|reklama"                    # HR / SL / LV / LT-BG
        ),
        # Functional / Preferences  (label → "Functional")
        (
            r"functional|functionality|preferences|personali[sz]ation"     # EN
            r"|egenskaper|funksjonell"                                      # NO
            r"|funktion\w*|préférences|functionele|voorkeuren"              # DE / FR / NL
            r"|funcional|funzionale|funkcjonalne|preferencje"               # ES-PT / IT / PL
            r"|funktionella|inställningar|toiminnalliset|asetukset"         # SV / FI
            r"|funkční|preference|funkcionális|beállítások"                 # CS / HU
            r"|funcționale|preferințe|funkcionalne|funktsionaalsed"         # RO / HR-SL / ET
        ),
        # Necessary / Essential / Required  (label → "Necessary")
        (
            r"necessary|essential|required|strictly|n[øo]dvendig"          # EN / NO
            r"|notwendig|erforderlich|nécessaire|noodzakelijk"              # DE / FR / NL
            r"|necesari[ao]s?|necessari[ao]s?|niezbędne|nödvändig"          # ES / IT-PT / PL / SV
            r"|nødvendig|välttämättömät|pakolliset|nezbytné"                # DA / FI / CS
            r"|nevyhnutné|szükséges|necesare|nužni|nujni"                   # SK / HU / RO / HR / SL
            r"|vajalikud|nepieciešamais|būtini|zadължителни"                # ET / LV / LT / BG
        ),
        # Social Media  (label → "Social")
        r"social.media|social media",
    ]
    consent_categories = []
    for pattern in category_patterns:
        if re.search(pattern, html_lower):
            label = pattern.split("|")[0].title()
            if label not in consent_categories:
                consent_categories.append(label)

    # Reject All availability — all major European languages
    reject_patterns = [
        # ── English ──────────────────────────────────────────────────────────
        "reject all", "reject-all", "rejectall",
        "decline all", "decline-all",
        "refuse all", "refuse-all",
        "deny all", "deny-all",
        "necessary only", "essential only",
        # ── Norwegian (Bokmål / Nynorsk) ─────────────────────────────────────
        "avvis alle",            # "reject all"
        "avvis-alle",
        "kun n\u00f8dvendig",    # "only necessary"
        "kun n\u00f8dvendige",
        "bare n\u00f8dvendige",  # "only necessary (plural)"
        "bare n\u00f8dvendig",
        # ── German ───────────────────────────────────────────────────────────
        "ablehnen", "alle ablehnen",
        "nur notwendige", "nur erforderliche",
        # ── French ───────────────────────────────────────────────────────────
        "tout refuser", "refuser tout",
        "uniquement nécessaires", "continuer sans accepter",
        # ── Dutch ────────────────────────────────────────────────────────────
        "alles weigeren",        # "refuse all"
        "weiger alle",           # "reject all"
        "alleen noodzakelijke",  # "only necessary"
        "alleen functionele",    # "only functional"
        # ── Spanish ──────────────────────────────────────────────────────────
        "rechazar todo",
        "rechazar todas",
        "solo necesarias",
        "denegar todo",
        "rechazar cookies",
        # ── Italian ──────────────────────────────────────────────────────────
        "rifiuta tutto",
        "rifiuta tutti",
        "solo necessari",
        "rifiuta i cookie",
        # ── Polish ───────────────────────────────────────────────────────────
        "odrzuć wszystkie",
        "odrzuć wszystko",
        "tylko niezbędne",
        "nie zgadzam się",
        # ── Portuguese ───────────────────────────────────────────────────────
        "rejeitar tudo",
        "recusar tudo",
        "apenas essenciais",
        "recusar cookies",
        # ── Swedish ──────────────────────────────────────────────────────────
        "avvisa alla",           # "reject all"
        "neka alla",             # "deny all"
        "bara nödvändiga",       # "only necessary"
        "avböj alla",            # "decline all"
        # ── Danish ───────────────────────────────────────────────────────────
        "afvis alle",            # "reject all"
        "kun nødvendige",        # "only necessary"
        "afvis cookies",
        # ── Finnish ──────────────────────────────────────────────────────────
        "hylkää kaikki",         # "reject all"
        "vain välttämättömät",   # "only necessary"
        "kieltäydy kaikesta",
        # ── Czech ────────────────────────────────────────────────────────────
        "odmítnout vše",         # "reject all"
        "jen nezbytné",          # "only necessary"
        "odmítnout cookies",
        # ── Slovak ───────────────────────────────────────────────────────────
        "odmietnuť všetky",      # "reject all"
        "len nevyhnutné",        # "only necessary"
        # ── Hungarian ────────────────────────────────────────────────────────
        "összes elutasítása",    # "reject all"
        "mindet elutasít",
        "csak szükséges",        # "only necessary"
        "elutasítás",
        # ── Romanian ─────────────────────────────────────────────────────────
        "refuzați toate",        # "refuse all"
        "respingeți toate",      # "reject all"
        "doar necesare",         # "only necessary"
        "refuz cookie-uri",
        # ── Croatian ─────────────────────────────────────────────────────────
        "odbij sve",             # "reject all"
        "samo nužni",            # "only necessary"
        "odbiti sve kolačiće",
        # ── Slovenian ────────────────────────────────────────────────────────
        "zavrni vse",            # "reject all"
        "samo nujni",            # "only necessary"
        # ── Estonian ─────────────────────────────────────────────────────────
        "lükka kõik tagasi",     # "reject all"
        "keeldu kõigest",        # "refuse everything"
        "ainult vajalikud",      # "only necessary"
        # ── Latvian ──────────────────────────────────────────────────────────
        "noraidīt visu",         # "reject all"
        "tikai nepieciešamais",  # "only necessary"
        # ── Lithuanian ───────────────────────────────────────────────────────
        "atmesti visus",         # "reject all"
        "tik būtini",            # "only necessary"
        # ── Bulgarian (Cyrillic) ─────────────────────────────────────────────
        "откажи всички",         # "reject all"
        "само необходими",       # "only necessary"
        # ── Greek ────────────────────────────────────────────────────────────
        "απόρριψη όλων",         # "reject all"
        "μόνο απαραίτητα",       # "only necessary"
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

    # ── Fallback: detect Consent Mode v2 from GCS network parameter ──────────
    # When the JS intercept misses the gtag() call (e.g. CMP fires too early),
    # the presence of ?gcs=G1XX in any GA4 collect request is a reliable CM v2
    # signal.  GCS encoding: G + <analytics_storage> + <ad_storage> + extras
    #   G100 = CM active, analytics denied, ad_storage denied  → compliant
    #   G111 = CM active, all granted  (seen after "Accept All")
    if not result.get("consent_mode_detected"):
        from consent_auditor import shared_state as _ss
        crawl = _ss.get("crawl", {})
        for req in crawl.get("network_requests", []):
            req_url = req.get("url", "")
            gcs_match = re.search(r"[?&]gcs=(G\d+)", req_url)
            if gcs_match:
                gcs_value = gcs_match.group(1)   # e.g. "G100" or "G111"
                result["consent_mode_detected"] = True
                result["consent_mode_version"] = "v2"
                result["gcs_initial_value"] = gcs_value

                # Parse per-digit consent states (digits after the leading G)
                digits = gcs_value[1:]   # "100" or "111"
                labels = ["analytics_storage", "ad_storage", "ad_user_data"]
                default_states = {}
                for i, digit in enumerate(digits):
                    if i < len(labels):
                        default_states[labels[i]] = "granted" if digit == "1" else "denied"
                if default_states:
                    result["default_states"] = default_states
                    all_denied = all(v == "denied" for v in default_states.values())
                    result["all_denied_by_default"] = all_denied
                    result["gdpr_consent_mode_compliant"] = all_denied
                break

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
_REJECT_TEXT_PATTERNS = re.compile(
    r"reject all|decline all|refuse all|deny all|no thanks"      # English
    r"|avvis alle|ablehnen|alle ablehnen|tout refuser"            # NO / DE / FR
    r"|alles weigeren|weiger alle|alleen noodzakelijke"           # NL
    r"|rechazar todo|rechazar todas|denegar todo"                 # ES
    r"|rifiuta tutto|rifiuta tutti|solo necessari"                # IT
    r"|odrzuć wszystkie|tylko niezbędne"                          # PL
    r"|rejeitar tudo|recusar tudo|apenas essenciais"              # PT
    r"|avvisa alla|neka alla|bara nödvändiga|avböj alla"          # SV
    r"|afvis alle|kun nødvendige"                                 # DA
    r"|hylkää kaikki|vain välttämättömät"                         # FI
    r"|odmítnout vše|jen nezbytné"                                # CS
    r"|odmietnuť všetky|len nevyhnutné"                           # SK
    r"|összes elutasítása|csak szükséges|elutasítás"              # HU
    r"|refuzați toate|respingeți toate|doar necesare"             # RO
    r"|odbij sve|samo nužni"                                      # HR
    r"|zavrni vse|samo nujni"                                     # SL
    r"|lükka kõik tagasi|ainult vajalikud"                        # ET
    r"|noraidīt visu|tikai nepieciešamais"                        # LV
    r"|atmesti visus|tik būtini"                                  # LT
    r"|откажи всички|само необходими"                             # BG
    r"|απόρριψη όλων|μόνο απαραίτητα",                            # EL
    re.I,
)
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
            pref_patterns = re.compile(
                r"manage|preferences|settings|customis|customiz"         # English
                r"|verwalten|einstellungen|anpassen"                      # German
                r"|gérer|paramètres|personnaliser"                        # French
                r"|beheren|instellingen|aanpassen"                        # Dutch
                r"|gestionar|configuración|personalizar"                  # Spanish
                r"|gestisci|impostazioni|personalizza"                    # Italian
                r"|zarządzaj|ustawienia|dostosuj"                         # Polish
                r"|gerir|configurações"                                   # Portuguese
                r"|hantera|inställningar|anpassa"                         # Swedish
                r"|administrer|indstillinger|tilpas"                      # Danish
                r"|hallinnoi|asetukset|mukauta"                           # Finnish
                r"|spravovat|nastavení|přizpůsobit"                       # Czech
                r"|spravovať|nastavenia|prispôsobiť"                      # Slovak
                r"|kezelés|beállítások|testreszab"                        # Hungarian
                r"|gestionați|setări|personalizați",                      # Romanian
                re.I,
            )
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
                        # English
                        "cookie", "privacy",
                        # German
                        "datenschutz", "impressum",
                        # French
                        "confidentialit", "politique",
                        # Dutch
                        "cookiebeleid", "privacybeleid",
                        # Norwegian
                        "personvern", "informasjonskapsler",
                        # Spanish
                        "privacidad", "política",
                        # Italian
                        "riservatezza", "informativa",
                        # Polish
                        "prywatności", "ciasteczka",
                        # Portuguese
                        "privacidade",
                        # Swedish
                        "integritetspolicy", "kakor",
                        # Danish
                        "cookiepolitik", "privatlivspolitik",
                        # Finnish
                        "tietosuoja", "evästeet",
                        # Czech
                        "soukromí",
                        # Hungarian
                        "adatvédelmi", "sütik",
                        # Romanian
                        "confidențialitate", "cookie-uri",
                        # Croatian
                        "kolačići",
                        # Estonian
                        "küpsised",
                        # Lithuanian
                        "slapukai",
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
                        # English
                        "analytics", "marketing", "functional", "necessary",
                        "essential", "performance", "advertising",
                        # German
                        "analyse", "werbung", "notwendig", "leistung",
                        # French
                        "analytique", "publicité", "nécessaire",
                        # Dutch
                        "analytisch", "noodzakelijk",
                        # Spanish
                        "analítica", "publicidad", "necesaria",
                        # Italian
                        "analitica", "pubblicità", "necessari",
                        # Polish
                        "analityczne", "marketingowe", "niezbędne",
                        # Portuguese
                        "publicidade", "necessários",
                        # Swedish
                        "marknadsföring", "nödvändig",
                        # Danish
                        "markedsføring", "nødvendig",
                        # Finnish
                        "analytiikka", "markkinointi", "välttämätön",
                        # Czech
                        "analytické", "marketingové", "nezbytné",
                        # Hungarian
                        "analitikai", "szükséges",
                        # Romanian
                        "analitice", "necesare",
                    ]
                    categories_listed = sum(1 for h in category_hints if h in html) >= 2

                    # Last updated date pattern
                    date_match = re.search(
                        r"(last\s+updated|updated\s+on|effective\s+date"          # English
                        r"|zuletzt\s+aktualisiert|letzte\s+aktualisierung"        # German
                        r"|derni[eè]re\s+mise\s+[aà]\s+jour|mis\s+[aà]\s+jour"   # French
                        r"|laatst\s+bijgewerkt"                                   # Dutch
                        r"|última\s+actualizaci[oó]n|actualizado\s+el"            # Spanish
                        r"|ultimo\s+aggiornamento"                                # Italian
                        r"|última\s+atualiza[çc][aã]o"                            # Portuguese
                        r"|ostatnia\s+aktualizacja"                               # Polish
                        r"|senast\s+uppdaterad"                                   # Swedish
                        r"|sidst\s+opdateret"                                     # Danish
                        r"|viimeksi\s+päivitetty"                                 # Finnish
                        r"|naposledy\s+aktualizov[aá]no"                          # Czech
                        r"|utoljára\s+frissítve"                                  # Hungarian
                        r"|actualizat\s+ultima\s+dat[aă]"                         # Romanian
                        r")[:\s]+([a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
                        html, re.I,
                    )
                    if date_match:
                        last_updated = date_match.group(2).strip()

                    dpo_hints = [
                        # English
                        "data protection officer", "dpo", "dpo@", "privacy@",
                        "contact us", "gdpr@", "compliance@",
                        # German
                        "datenschutzbeauftragter", "datenschutzbeauftragte",
                        "datenschutz@",
                        # French
                        "délégué à la protection des données", "dpd@",
                        "responsable de la protection",
                        # Dutch
                        "functionaris voor gegevensbescherming", "fg@",
                        "privacyofficer",
                        # Spanish
                        "delegado de protección de datos",
                        # Italian
                        "responsabile della protezione dei dati",
                        # Polish
                        "inspektor ochrony danych", "iod@",
                        # Swedish
                        "dataskyddsombud",
                        # Danish
                        "databeskyttelsesrådgiver",
                        # Finnish
                        "tietosuojavastaava",
                        # Czech
                        "pověřenec pro ochranu osobních údajů",
                        # Hungarian
                        "adatvédelmi tisztviselő",
                        # Romanian
                        "responsabil cu protecția datelor",
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
