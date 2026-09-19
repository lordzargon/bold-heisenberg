"""
Automated URL Healer & Career Page Health Monitor
Detects broken/moved career pages, self-heals URLs, identifies parked/for-sale domains,
and updates companies.json automatically.
"""

import os
import sys
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
import socket
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANIES_DB_FILE = os.path.join(SCRIPT_DIR, "companies.json")
FAILED_PAGES_JSON = os.path.join(SCRIPT_DIR, "failed_job_pages.json")
FAILED_PAGES_MD = os.path.join(SCRIPT_DIR, "failed_job_pages.md")
HEALED_REPORT_MD = os.path.join(SCRIPT_DIR, "healed_pages_report.md")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,application/json,*/*;q=0.8',
    'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
    'Sec-Ch-Ua': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}

class SmartRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    Subclass HTTPRedirectHandler to explicitly support HTTP 308 (Permanent Redirect)
    and ensure redirects are safely followed across modern web servers.
    """
    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, code, msg, headers)

SMART_OPENER = urllib.request.build_opener(
    SmartRedirectHandler(),
    urllib.request.HTTPSHandler(context=SSL_CTX)
)
urllib.request.install_opener(SMART_OPENER)

KNOWN_PARKING_BROKERS = {
    "brandsly.com", "efty.com", "sedo.com", "dan.com", "afternic.com",
    "hugedomains.com", "domainmarket.com", "atom.com", "squadhelp.com",
    "parkingcrew.net", "bodis.com", "sedoparking.com", "domainagents.com",
    "undeveloped.com", "godaddy.com", "namecheap.com", "flippa.com"
}

PARKING_KEYWORDS = [
    "this domain is for sale",
    "buy this domain",
    "domain may be for sale",
    "inquire about this domain",
    "domain name is available for purchase",
    "this domain has expired",
    "is parked free",
    "domain parked",
    "renew your domain",
    "parked by godaddy",
    "purchase this domain",
    "make an offer on this domain",
    "is available for sale on dan.com",
    "domain broker",
    "the domain name is available for sale",
]

NO_VACANCY_SIGNATURES = [
    "no open positions",
    "no vacancies at present",
    "no current vacancies",
    "we are not currently hiring",
    "not actively hiring",
    "no current openings",
    "no active openings",
    "check back soon for future openings",
    "no roles available",
    "there are currently no vacancies",
    "no vacancies currently available",
    "we don't have any open positions",
    "no job openings at this time",
    "we currently have no open roles",
]

COMMON_CAREER_PATHS = [
    "/careers",
    "/jobs",
    "/vacancies",
    "/join-us",
    "/join",
    "/work-with-us",
    "/work",
    "/about/careers",
    "/about/jobs",
    "/open-roles",
    "/opportunities",
    "/careers/",
    "/jobs/",
    "/vacancies/",
    "/join-us/",
    "/work-with-us/",
]

def fetch_page(url, timeout=10):
    """
    Fetches URL with full redirect resolution, permissive SSL, and modern browser headers.
    Returns: (status_code, final_url, html_content, error_msg)
    """
    if not url or not url.startswith(("http://", "https://")):
        return 0, url, "", "Invalid URL format"

    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    try:
        with SMART_OPENER.open(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            status_code = getattr(resp, 'status', 200)
            raw = resp.read()
            html = raw.decode('utf-8', errors='replace')
            return status_code, final_url, html, None
    except urllib.error.HTTPError as he:
        final_url = he.geturl() if hasattr(he, 'geturl') else url
        err_msg = f"HTTP {he.code} ({he.reason})"
        try:
            body = he.read().decode('utf-8', errors='replace')
        except Exception:
            body = ""
        return he.code, final_url, body, err_msg
    except urllib.error.URLError as ue:
        return 0, url, "", f"URLError: {ue.reason}"
    except (socket.timeout, TimeoutError):
        return 0, url, "", "Connection Timeout (>10s)"
    except Exception as e:
        return 0, url, "", f"Error: {e}"

def is_domain_parked(url, html=""):
    """
    Detects if a URL or its landed page belongs to a domain broker or parking service.
    Returns: (is_parked, reason)
    """
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]

    # 1. Check if domain or redirect belongs to a known parking broker
    for broker in KNOWN_PARKING_BROKERS:
        if broker in domain:
            return True, f"Redirected to domain sales broker: {broker}"

    # 2. Check content for parked/sales copy
    if html:
        content_lower = html.lower()
        matched_indicators = [kw for kw in PARKING_KEYWORDS if kw in content_lower]
        if len(matched_indicators) >= 1:
            return True, f"Detected domain parking text: '{matched_indicators[0]}'"

    return False, None

def check_no_vacancies_text(html):
    """
    Detects if a 200 OK page contains unambiguous copy stating zero open vacancies.
    """
    if not html:
        return False, None
    html_lower = html.lower()
    for phrase in NO_VACANCY_SIGNATURES:
        if phrase in html_lower:
            return True, phrase
    return False, None

def detect_ats_type(url):
    """Identifies the ATS platform type from a candidate career URL."""
    url_lower = url.lower()
    if "boards.greenhouse.io" in url_lower:
        return "greenhouse"
    if "jobs.lever.co" in url_lower:
        return "lever"
    if "jobs.ashbyhq.com" in url_lower:
        return "ashby"
    if "workable.com" in url_lower:
        return "workable"
    if "teamtailor.com" in url_lower:
        return "teamtailor"
    if "recruitee.com" in url_lower:
        return "recruitee"
    if "pinpointhq.com" in url_lower:
        return "pinpoint"
    if "bamboohr.com" in url_lower:
        return "bamboohr"
    return "custom_html"

def probe_common_paths(base_url):
    """
    Probes standard career path extensions on the studio's domain.
    Returns: (working_url, ats_type, html) or (None, None, None)
    """
    parsed = urllib.parse.urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    for path in COMMON_CAREER_PATHS:
        target = f"{root}{path}"
        if target.rstrip('/') == base_url.rstrip('/'):
            continue
            
        status, final_url, html, err = fetch_page(target, timeout=7)
        if status == 200 and html:
            # Verify not parked
            parked, _ = is_domain_parked(final_url, html)
            if parked:
                continue

            # Check if this page has career indicators
            ats_type = detect_ats_type(final_url)
            if ats_type != "custom_html":
                return final_url, ats_type, html

            html_lower = html.lower()
            indicators = ["job", "career", "vacancy", "vacancies", "position", "opening", "work with us", "apply", "join us"]
            found_indicators = sum(1 for ind in indicators if ind in html_lower)
            if found_indicators >= 2:
                return final_url, "custom_html", html

    return None, None, None

def extract_career_links_from_homepage(homepage_url):
    """
    Fetches homepage root and extracts potential career links from anchors.
    Prioritizes ATS URLs, then explicit 'careers' / 'jobs' anchor texts.
    """
    status, final_url, html, err = fetch_page(homepage_url, timeout=10)
    if status != 200 or not html:
        return []

    # Check if homepage itself is parked
    parked, _ = is_domain_parked(final_url, html)
    if parked:
        return []

    ats_links = []
    career_links = []

    link_pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    career_anchor_re = re.compile(r'\b(careers?|jobs?|vacanc(?:y|ies)|join\s*us|work\s*with\s*us|working\s*with\s*us|open\s*roles?|openings)\b', re.I)

    for href, text in link_pattern.findall(html):
        href = href.strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue

        full_url = urllib.parse.urljoin(final_url, href)
        clean_text = re.sub(r'<[^>]+>', '', text).strip()

        # 1. External ATS links
        ats_type = detect_ats_type(full_url)
        if ats_type != "custom_html":
            ats_links.append(full_url)
            continue

        # 2. Career anchor text or URL path match
        parsed_href = urllib.parse.urlparse(full_url)
        href_path = parsed_href.path.lower()
        if career_anchor_re.search(clean_text) or any(p in href_path for p in ["/career", "/job", "/vacanc", "/join", "/work"]):
            if not any(s in full_url.lower() for s in ["linkedin.com", "twitter.com", "facebook.com", "youtube.com", "instagram.com"]):
                career_links.append(full_url)

    unique_links = []
    for link in (ats_links + career_links):
        if link not in unique_links:
            unique_links.append(link)
    return unique_links

def load_companies():
    """Loads companies database from companies.json."""
    if os.path.exists(COMPANIES_DB_FILE):
        try:
            with open(COMPANIES_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Error loading {COMPANIES_DB_FILE}: {e}")
    return {}

def save_companies(companies_data):
    """Saves companies database atomically."""
    tmp_path = f"{COMPANIES_DB_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(companies_data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, COMPANIES_DB_FILE)

def heal_single_target(item):
    """
    Diagnoses and attempts to self-heal a single failed company entry.
    Returns a result dict with update_fields for batch application.
    """
    comp_name = item.get("company", "Unknown Studio")
    careers_url = item.get("url", "")
    error_type = item.get("error_type", "")
    detail = item.get("detail", "")

    result = {
        "company": comp_name,
        "original_url": careers_url,
        "original_error": error_type,
        "action_taken": "unresolved",
        "new_url": None,
        "new_type": None,
        "status_tag": "needs_review",
        "notes": "",
        "update_fields": None
    }

    if not careers_url or careers_url == "Recruiter Board" or not careers_url.startswith(("http://", "https://")):
        result["notes"] = "Non-standard URL / Recruiter board skipped"
        return result

    # Step 1: Check initial page state (follow redirects, see what it actually lands on)
    status, final_url, html, err = fetch_page(careers_url, timeout=10)

    # 1A: Check if landed domain is parked / for sale
    is_parked, park_reason = is_domain_parked(final_url, html)
    if is_parked:
        result["action_taken"] = "flagged_defunct"
        result["status_tag"] = "domain_for_sale"
        result["notes"] = park_reason
        result["update_fields"] = {
            "status": "defunct",
            "defunct_reason": park_reason,
            "defunct_detected_at": datetime.datetime.now().isoformat()
        }
        return result

    # 1B: If 403 Forbidden (Cloudflare / Bot block)
    if status == 403:
        result["action_taken"] = "bot_protection_detected"
        result["status_tag"] = "protected_cloudflare"
        result["notes"] = "Blocked by Cloudflare/WAF bot check (loads fine in human browser)"
        return result

    # 1C: If 200 OK (Loaded fine)
    if status == 200:
        # If redirected to a new canonical URL (e.g. HTTP 308 or redirect to jobs.poki.com)
        if final_url.rstrip('/') != careers_url.rstrip('/'):
            ats = detect_ats_type(final_url)
            result["action_taken"] = "healed_redirect"
            result["new_url"] = final_url
            result["new_type"] = ats
            result["status_tag"] = "healed"
            result["notes"] = f"Permanently redirected to canonical URL: {final_url}"
            result["update_fields"] = {
                "careers_url": final_url,
                "careers_type": ats,
                "website_status": 200,
                "healed_at": datetime.datetime.now().isoformat()
            }
            return result

        # Check if page has explicit 'no vacancies' copy
        has_no_vac, vac_phrase = check_no_vacancies_text(html)
        if has_no_vac:
            result["action_taken"] = "verified_healthy_empty"
            result["status_tag"] = "healthy_no_vacancies"
            result["notes"] = f"Page verified healthy; explicitly states: '{vac_phrase}'"
            result["update_fields"] = {
                "website_status": 200,
                "vacancies_status": "none_active",
                "last_verified_empty": datetime.datetime.now().isoformat()
            }
            return result
        else:
            result["action_taken"] = "verified_healthy"
            result["status_tag"] = "healthy"
            result["notes"] = "Page returns 200 OK with no errors"
            result["update_fields"] = {
                "website_status": 200,
                "last_verified_ok": datetime.datetime.now().isoformat()
            }
            return result

    # Step 2: If 404 or connection error, attempt path drift probing
    parsed = urllib.parse.urlparse(careers_url)
    root_domain = f"{parsed.scheme}://{parsed.netloc}"

    working_url, ats_type, _ = probe_common_paths(careers_url)
    if working_url:
        result["action_taken"] = "healed_path_probe"
        result["new_url"] = working_url
        result["new_type"] = ats_type
        result["status_tag"] = "healed"
        result["notes"] = f"Auto-discovered active path: {working_url}"
        result["update_fields"] = {
            "careers_url": working_url,
            "careers_type": ats_type,
            "website_status": 200,
            "healed_at": datetime.datetime.now().isoformat()
        }
        return result

    # Step 3: Spider homepage root for ATS embeds or career links
    candidate_links = extract_career_links_from_homepage(root_domain)
    for cand in candidate_links:
        c_status, c_final, c_html, _ = fetch_page(cand, timeout=8)
        if c_status == 200 and c_html:
            is_c_parked, _ = is_domain_parked(c_final, c_html)
            if not is_c_parked:
                c_ats = detect_ats_type(c_final)
                result["action_taken"] = "healed_homepage_spider"
                result["new_url"] = c_final
                result["new_type"] = c_ats
                result["status_tag"] = "healed"
                result["notes"] = f"Discovered on homepage navigation: {c_final}"
                result["update_fields"] = {
                    "careers_url": c_final,
                    "careers_type": c_ats,
                    "website_status": 200,
                    "healed_at": datetime.datetime.now().isoformat()
                }
                return result

    # Step 4: Check if root domain itself is parked
    root_status, root_final, root_html, _ = fetch_page(root_domain, timeout=8)
    if is_domain_parked(root_final, root_html)[0]:
        park_msg = "Root domain is for sale / parked"
        result["action_taken"] = "flagged_defunct"
        result["status_tag"] = "domain_for_sale"
        result["notes"] = park_msg
        result["update_fields"] = {
            "status": "defunct",
            "defunct_reason": park_msg,
            "defunct_detected_at": datetime.datetime.now().isoformat()
        }
        return result

    result["notes"] = f"Unresolved {error_type}. Direct paths and homepage search did not find an active career portal."
    return result

def apply_batch_updates(results):
    """Applies all diagnosis updates to companies.json in a single atomic transaction."""
    companies_db = load_companies()
    if not companies_db:
        return 0

    name_to_id = {}
    for cid, comp in companies_db.items():
        name_lower = comp.get("name", "").lower().strip()
        if name_lower:
            name_to_id[name_lower] = cid

    updated_count = 0
    for r in results:
        uf = r.get("update_fields")
        if not uf:
            continue
        cname = r.get("company", "").lower().strip()
        cid = name_to_id.get(cname)
        if cid and cid in companies_db:
            for k, v in uf.items():
                companies_db[cid][k] = v
            updated_count += 1

    if updated_count > 0:
        save_companies(companies_db)
        print(f"[*] Updated {updated_count} company records in companies.json")
    return updated_count

def update_failed_pages_reports_after_healing(results):
    """
    Refreshes failed_job_pages.json and failed_job_pages.md so that healed,
    defunct, and verified-healthy pages are cleanly removed from the manual failure list.
    """
    if not os.path.exists(FAILED_PAGES_JSON):
        return

    try:
        with open(FAILED_PAGES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            original_failures = data.get("failures", [])
    except Exception:
        return

    # Studios to remove from active failures
    resolved_companies = set()
    for r in results:
        if r.get("status_tag") in ("healed", "domain_for_sale", "healthy_no_vacancies", "healthy"):
            resolved_companies.add(r.get("company", "").lower().strip())

    remaining_failures = [f for f in original_failures if f.get("company", "").lower().strip() not in resolved_companies]

    now_iso = datetime.datetime.now().isoformat()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Save JSON
    json_data = {
        "generated_at": now_iso,
        "total_failed": len(remaining_failures),
        "failures": remaining_failures
    }
    with open(FAILED_PAGES_JSON, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    # Save MD
    lines = [
        "# Failed / Timed Out Career & Job Listing Pages",
        f"\n*Generated on {now_str}*",
        f"\nTotal Pages Requiring Manual Check: **{len(remaining_failures)}**\n"
    ]
    if not remaining_failures:
        lines.append("> [!NOTE]\n> All career pages responded successfully or have been auto-healed. No failures remain.\n")
    else:
        lines.append("> [!WARNING]\n> The following studio career pages or job widgets encountered errors that require manual check.\n")
        lines.append("| Studio | Source / ATS | Error Type | Details | Direct Link |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for item in sorted(remaining_failures, key=lambda x: (x.get("status") != "timeout", x.get("company", "").lower())):
            comp = item.get("company", "Unknown")
            src = item.get("source", "Web")
            err_type = item.get("error_type", "Error")
            detail = item.get("detail", "").replace("|", "/")
            url = item.get("url", "#")
            lines.append(f"| **{comp}** | {src} | `{err_type}` | {detail} | [Open Careers Page]({url}) |")

    with open(FAILED_PAGES_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

def heal_failed_pages(failed_list=None, max_workers=6):
    """
    Main entrypoint: analyzes all failed entries, applies self-healing,
    updates database in batch, and generates a structured report.
    """
    if failed_list is None:
        if os.path.exists(FAILED_PAGES_JSON):
            with open(FAILED_PAGES_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                failed_list = data.get("failures", [])
        else:
            failed_list = []

    if not failed_list:
        print("[*] No failed pages to heal.")
        return []

    print(f"[*] Starting Automated URL Healing for {len(failed_list)} sites (Workers: {max_workers})...")
    healed_results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(heal_single_target, item): item for item in failed_list}
        completed = 0
        for future in as_completed(future_to_item):
            completed += 1
            item = future_to_item[future]
            try:
                res = future.result()
                healed_results.append(res)
                icon = "[HEALED]" if "healed" in res["action_taken"] else ("[DEFUNCT]" if "defunct" in res["action_taken"] else ("[EMPTY]" if "empty" in res["action_taken"] else "[CHECK]"))
                clean_notes = res['notes'][:50].replace('\n', ' ')
                print(f"[{completed}/{len(failed_list)}] {icon} {res['company']}: {res['action_taken']} ({clean_notes})")
            except Exception as e:
                print(f"[!] Error processing {item.get('company')}: {e}")

    # 1. Apply database updates in a single batch
    apply_batch_updates(healed_results)

    # 2. Update failed_job_pages list to remove resolved entries
    update_failed_pages_reports_after_healing(healed_results)

    # 3. Generate detailed Markdown report
    save_healed_report(healed_results)
    return healed_results

def save_healed_report(results):
    """Generates healed_pages_report.md summarizing auto-healing actions."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    healed = [r for r in results if "healed" in r["action_taken"]]
    defunct = [r for r in results if "defunct" in r["action_taken"]]
    quiet = [r for r in results if "empty" in r["action_taken"] or "healthy" in r["action_taken"]]
    protected = [r for r in results if "protected" in r["status_tag"]]
    unresolved = [r for r in results if r["status_tag"] == "needs_review"]

    lines = [
        "# Automated Career URL Health & Healing Report",
        f"\n*Generated on {now_str}*\n",
        f"| Metric | Count |",
        f"| :--- | :--- |",
        f"| 🔧 **Successfully Auto-Healed** | **{len(healed)}** |",
        f"| 🏷️ **Flagged Defunct / Domain For Sale** (Silenced) | **{len(defunct)}** |",
        f"| 💤 **Verified Healthy (0 Vacancies)** | **{len(quiet)}** |",
        f"| 🛡️ **Protected (Cloudflare 403)** | **{len(protected)}** |",
        f"| ⚠️ **Unresolved (Requires Manual Look)** | **{len(unresolved)}** |\n"
    ]

    if healed:
        lines.append("## 🔧 Auto-Healed URLs (Updated in companies.json)\n")
        lines.append("| Studio | New Career URL | ATS Type | Discovery Method |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for h in sorted(healed, key=lambda x: x["company"].lower()):
            lines.append(f"| **{h['company']}** | [{h['new_url']}]({h['new_url']}) | `{h['new_type']}` | {h['notes']} |")
        lines.append("")

    if defunct:
        lines.append("## 🏷️ Defunct Studios / Domains For Sale (Silenced)\n")
        lines.append("| Studio | Original URL | Reason Detected |")
        lines.append("| :--- | :--- | :--- |")
        for d in sorted(defunct, key=lambda x: x["company"].lower()):
            lines.append(f"| **{d['company']}** | {d['original_url']} | {d['notes']} |")
        lines.append("")

    if quiet:
        lines.append("## 💤 Verified Healthy Studios (0 Active Vacancies)\n")
        lines.append("| Studio | URL | Verification Detail |")
        lines.append("| :--- | :--- | :--- |")
        for q in sorted(quiet, key=lambda x: x["company"].lower()):
            lines.append(f"| **{q['company']}** | [{q['original_url']}]({q['original_url']}) | {q['notes']} |")
        lines.append("")

    if protected:
        lines.append("## 🛡️ Bot-Protected Studios (Cloudflare 403)\n")
        lines.append("> [!NOTE]\n> These pages loaded fine in your personal browser because desktop browsers pass Cloudflare checks. You can safely inspect these manually.\n")
        lines.append("| Studio | Direct Link |")
        lines.append("| :--- | :--- |")
        for p in sorted(protected, key=lambda x: x["company"].lower()):
            lines.append(f"| **{p['company']}** | [Open Site]({p['original_url']}) |")
        lines.append("")

    if unresolved:
        lines.append("## ⚠️ Unresolved / Dead Links\n")
        lines.append("| Studio | Error | Detail | Direct Link |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for u in sorted(unresolved, key=lambda x: x["company"].lower()):
            lines.append(f"| **{u['company']}** | `{u['original_error']}` | {u['notes']} | [Open Site]({u['original_url']}) |")
        lines.append("")

    with open(HEALED_REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[*] Report saved to {HEALED_REPORT_MD}")

if __name__ == "__main__":
    heal_failed_pages()
