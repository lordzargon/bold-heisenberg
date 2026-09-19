"""
Career Page Job Monitor & Tech Artist Extractor
Scans discovered game studio career pages, detects new openings,
extracts Tech Artist roles, and sends notifications.
"""

import os
import sys
import re
import time
import json
import random
import urllib.request
import urllib.parse
import urllib.error
import ssl
import socket
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure hard global socket timeout so no network call can ever hang indefinitely
socket.setdefaulttimeout(10.0)
try:
    from geo_utils import evaluate_location_rules
except ImportError:
    evaluate_location_rules = None

try:
    from recruiter_monitor import fetch_all_recruiter_jobs
except ImportError:
    fetch_all_recruiter_jobs = None

try:
    from gamesjobsindex_monitor import fetch_gamesjobsindex_jobs
except ImportError:
    fetch_gamesjobsindex_jobs = None

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANIES_DB_FILE = os.path.join(SCRIPT_DIR, "companies.json")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
SEEN_JOBS_FILE = os.path.join(SCRIPT_DIR, "seen_career_jobs.json")
TECH_ART_REPORT_JSON = os.path.join(SCRIPT_DIR, "tech_artist_jobs.json")
TECH_ART_REPORT_MD = os.path.join(SCRIPT_DIR, "tech_artist_roles_found.md")
FAILED_PAGES_JSON = os.path.join(SCRIPT_DIR, "failed_job_pages.json")
FAILED_PAGES_MD = os.path.join(SCRIPT_DIR, "failed_job_pages.md")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

class SmartRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, code, msg, headers)

SMART_OPENER = urllib.request.build_opener(
    SmartRedirectHandler(),
    urllib.request.HTTPSHandler(context=SSL_CTX)
)
urllib.request.install_opener(SMART_OPENER)

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

def load_config():
    target_path = CONFIG_PATH
    if not os.path.exists(target_path):
        example_path = os.path.join(SCRIPT_DIR, "config.example.json")
        if os.path.exists(example_path):
            target_path = example_path
    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Warning reading config ({target_path}): {e}")
    return {
        "search": {
            "keywords": [
                "technical artist",
                "tech artist",
                "technical art",
                "character technical artist",
                "character tech artist",
                "technical animator",
                "tech anim",
                "pipeline technical director",
                "pipeline td",
                "art td",
                "art technical director",
                "technical art director",
                "tools artist",
                "tools engineer",
                "tools programmer",
                "tools developer",
                "pipeline engineer",
                "pipeline developer",
                "vfx technical artist",
                "vfx tech artist",
                "shader artist",
                "shader engineer",
                "shader programmer",
                "shader developer",
                "rendering engineer",
                "rendering programmer",
                "graphics engineer",
                "graphics programmer",
                "graphics technical artist",
                "graphics tech artist",
                "performance engineer",
                "optimization engineer",
                "lighting technical artist",
                "technical lighting artist",
                "rigging artist",
                "rigging technical artist",
                "rigger",
                "environment technical artist"
            ],
            "exclude_keywords": [
                "unpaid",
                "subsea",
                "civil engineer",
                "oil and gas",
                "drilling"
            ],
            "location_filter": [],
            "remote_only": False
        },
        "notifications": {
            "windows_toast": True,
            "discord_webhook_url": "",
            "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
            "slack_webhook_url": ""
        }
    }

def load_seen_jobs():
    if os.path.exists(SEEN_JOBS_FILE):
        try:
            with open(SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
                elif isinstance(data, dict):
                    return set(data.get("seen_ids", []))
        except Exception as e:
            print(f"[!] Warning reading seen jobs DB: {e}")
    return set()

def save_seen_jobs(seen_ids):
    data = {
        "last_updated": datetime.datetime.now().isoformat(),
        "total_seen": len(seen_ids),
        "seen_ids": list(seen_ids)
    }
    with open(SEEN_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

try:
    from date_utils import parse_date_to_timestamp
except ImportError:
    def parse_date_to_timestamp(date_val):
        return str(date_val)[:10] if date_val else "", 0.0

def classify_fetch_error(err):
    """Categorizes exceptions into structured status and readable descriptions."""
    if isinstance(err, urllib.error.HTTPError):
        if err.code == 429:
            return "rate_limited", "HTTP 429 (Rate Limited / Throttled)"
        elif err.code == 403:
            return "forbidden", "HTTP 403 (Access Forbidden / Cloudflare)"
        elif err.code == 404:
            return "not_found", "HTTP 404 (Page Not Found)"
        elif err.code == 504:
            return "gateway_timeout", "HTTP 504 (Gateway Timeout)"
        elif err.code in (500, 502, 503):
            return "server_error", f"HTTP {err.code} (Server Error)"
        return "http_error", f"HTTP {err.code} ({err.reason})"
    elif isinstance(err, (socket.timeout, TimeoutError)):
        return "timeout", "Connection Timeout (Request took >10s)"
    elif isinstance(err, urllib.error.URLError):
        reason = getattr(err, 'reason', None)
        reason_str = str(reason)
        if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in reason_str.lower():
            return "timeout", "Connection Timeout (Request took >10s)"
        if "temporary failure in name resolution" in reason_str.lower() or "getaddrinfo failed" in reason_str.lower():
            return "dns_error", f"DNS Resolution Failed: {reason_str}"
        return "network_error", f"Network Error: {reason_str}"
    else:
        err_str = str(err)
        if "timed out" in err_str.lower():
            return "timeout", "Connection Timeout (Request took >10s)"
        return "error", f"Error: {err_str}"

def save_failed_pages_reports(failed_pages):
    """
    Saves failed/timed-out career pages to both failed_job_pages.json
    and failed_job_pages.md for easy manual inspection.
    """
    now_iso = datetime.datetime.now().isoformat()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. JSON Report
    json_data = {
        "generated_at": now_iso,
        "total_failed": len(failed_pages),
        "failures": failed_pages
    }
    with open(FAILED_PAGES_JSON, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    # 2. Markdown Report
    lines = [
        "# Failed / Timed Out Career & Job Listing Pages",
        f"\n*Generated on {now_str}*",
        f"\nTotal Pages Requiring Manual Check: **{len(failed_pages)}**\n"
    ]

    if not failed_pages:
        lines.append("> [!NOTE]\n> All career pages responded successfully during the latest check. No timeouts or errors recorded.\n")
    else:
        lines.append("> [!WARNING]\n> The following studio career pages or job widgets timed out or encountered errors (such as throttling or Cloudflare blocks). Use the links below to manually review these sites.\n")
        lines.append("| Studio | Source / ATS | Error Type | Details | Direct Link |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for item in sorted(failed_pages, key=lambda x: (x.get("status") != "timeout", x.get("company", "").lower())):
            comp = item.get("company", "Unknown")
            src = item.get("source", "Web")
            err_type = item.get("error_type", "Error")
            detail = item.get("detail", "").replace("|", "/")
            url = item.get("url", "#")
            lines.append(f"| **{comp}** | {src} | `{err_type}` | {detail} | [Open Careers Page]({url}) |")

    with open(FAILED_PAGES_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

def fetch_greenhouse_jobs(board_token, company_name):
    """Fetches jobs via Greenhouse public JSON API"""
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        jobs = []
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        for j in data.get("jobs", []):
            loc = (j.get("location", {}) or {}).get("name", "")
            title = j.get("title", "").strip()
            updated_raw = j.get("updated_at") or ""
            disp_date, ts = parse_date_to_timestamp(updated_raw)
            full_text = f"{title} {loc}".lower()
            jobs.append({
                "id": f"gh_{j.get('id')}",
                "title": title,
                "company": company_name,
                "location": loc,
                "hybrid": "hybrid" in full_text,
                "remote": "remote" in full_text,
                "url": j.get("absolute_url", ""),
                "department": ((j.get("departments") or [{}])[0]).get("name", ""),
                "source": "Greenhouse",
                "date_posted": disp_date,
                "date_posted_ts": ts,
                "date_added_ts": now_ts,
            })
        return jobs

def fetch_lever_jobs(site_name, company_name):
    """Fetches jobs via Lever public JSON API"""
    api_url = f"https://api.lever.co/v0/postings/{site_name}?mode=json"
    req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        jobs = []
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        for j in data:
            categories = j.get("categories", {}) or {}
            loc = categories.get("location", "")
            title = j.get("text", "").strip()
            workplace_type = (categories.get("workplaceType") or "").lower()
            created_raw = j.get("createdAt")
            disp_date, ts = parse_date_to_timestamp(created_raw)
            full_text = f"{title} {loc} {workplace_type}".lower()
            jobs.append({
                "id": f"lever_{j.get('id')}",
                "title": title,
                "company": company_name,
                "location": loc,
                "hybrid": "hybrid" in full_text or workplace_type == "hybrid",
                "remote": "remote" in full_text or workplace_type == "remote",
                "url": j.get("hostedUrl", ""),
                "department": categories.get("department", ""),
                "source": "Lever",
                "date_posted": disp_date,
                "date_posted_ts": ts,
                "date_added_ts": now_ts,
            })
        return jobs

def fetch_ashby_jobs(org_name, company_name):
    """Fetches jobs via Ashby public API"""
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{org_name}"
    req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        jobs = []
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        for j in data.get("jobs", []):
            loc = j.get("location", "")
            title = j.get("title", "").strip()
            pub_raw = j.get("publishedAt") or j.get("openedAt") or ""
            disp_date, ts = parse_date_to_timestamp(pub_raw)
            workplace_type = (j.get("workplaceType") or "").lower()
            full_text = f"{title} {loc} {workplace_type}".lower()
            jobs.append({
                "id": f"ashby_{j.get('id')}",
                "title": title,
                "company": company_name,
                "location": loc,
                "hybrid": "hybrid" in full_text or workplace_type == "hybrid",
                "remote": "remote" in full_text or workplace_type == "remote" or j.get("isRemote", False),
                "url": j.get("jobUrl", ""),
                "department": j.get("department", ""),
                "source": "Ashby",
                "date_posted": disp_date,
                "date_posted_ts": ts,
                "date_added_ts": now_ts,
            })
        return jobs

def fetch_workable_jobs(account_slug, company_name):
    """Fetches jobs via Workable public Widget JSON API"""
    api_url = f"https://apply.workable.com/api/v1/widget/accounts/{account_slug}"
    req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        jobs = []
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        for j in data.get("jobs", []):
            loc_parts = [j.get("city"), j.get("state"), j.get("country")]
            loc_str = ", ".join([p for p in loc_parts if p])
            title = j.get("title", "").strip()
            created_raw = j.get("created_at") or j.get("published_on") or ""
            disp_date, ts = parse_date_to_timestamp(created_raw)
            workplace_type = (j.get("workplace_type") or "").lower()
            full_text = f"{title} {loc_str} {workplace_type}".lower()
            jobs.append({
                "id": f"workable_{j.get('shortcode') or j.get('code')}",
                "title": title,
                "company": company_name,
                "location": loc_str or "UK / Remote",
                "hybrid": "hybrid" in full_text or workplace_type == "hybrid",
                "remote": j.get("telecommuting", False) or "remote" in full_text or workplace_type == "remote",
                "url": j.get("url") or j.get("shortlink") or j.get("application_url", ""),
                "department": j.get("department", ""),
                "source": "Workable",
                "date_posted": disp_date,
                "date_posted_ts": ts,
                "date_added_ts": now_ts,
            })
        return jobs

def fetch_html_career_page_jobs(careers_url, company_name, failed_recorder=None):
    """
    Parses generic HTML career pages to extract job links and job titles with high precision.
    """
    try:
        req = urllib.request.Request(careers_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        if failed_recorder:
            failed_recorder("Direct Web", e, careers_url)
        return []

    # Check if this HTML page delegates to Workable
    slug = None
    wm_apply = re.search(r'apply\.workable\.com/(?:api/v\d+/widget/accounts/)?([a-zA-Z0-9_\-]+)', html)
    if wm_apply:
        slug = wm_apply.group(1)
    else:
        wm_sub = re.search(r'([a-zA-Z0-9_\-]+)\.workable\.com', html)
        if wm_sub:
            slug = wm_sub.group(1)

    workable_reserved = {"jobs", "j", "api", "widget", "www", "embed", "assets", "resources", "help", "support", "static"}
    if slug and slug.lower() not in workable_reserved:
        try:
            w_jobs = fetch_workable_jobs(slug, company_name)
            if w_jobs:
                return w_jobs
        except Exception as we:
            if failed_recorder:
                failed_recorder("Workable Widget", we, f"https://apply.workable.com/{slug}/")
    
    jobs = []
    link_pattern = r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
    
    # Non-job noise words to reject
    ignore_keywords = [
        "home", "about", "contact", "privacy", "terms", "cookies", "login", "sign in", "sign up",
        "apply now", "read more", "view all", "learn more", "partners", "partner", "articles",
        "news", "blog", "events", "press", "services", "solutions", "sectors", "clients",
        "all rights reserved", "subscribe", "newsletter", "cookie policy", "terms of use",
        "startups", "start building", "find a partner", "facebook", "twitter", "linkedin",
        "instagram", "youtube", "discord", "twitch", "technology", "our team", "who we are"
    ]
    
    # Common job-related words in titles or links
    job_indicators = [
        "artist", "engineer", "developer", "programmer", "designer", "producer", "animator",
        "director", "lead", "senior", "junior", "mid", "principal", "manager", "specialist",
        "associate", "tester", "qa", "intern", "tech", "audio", "writer", "architect", "td"
    ]
    
    for href, text in re.findall(link_pattern, html, re.DOTALL | re.IGNORECASE):
        clean_title = re.sub(r'<[^>]+>', '', text).strip()
        clean_title = re.sub(r'\s+', ' ', clean_title)
        clean_lower = clean_title.lower()
        href_lower = href.lower()

        # Clean trailing noise words like 'LEARN MORE', 'APPLY NOW'
        for noise in ["learn more", "apply now", "view role", "view job", "read more", "apply"]:
            if clean_lower.endswith(noise) and len(clean_lower) > len(noise) + 3:
                clean_title = clean_title[:len(clean_title)-len(noise)].strip(" -:|•")
                clean_lower = clean_title.lower()
        
        # Check length
        if 5 <= len(clean_title) <= 80:
            # Filter out navigation/noise words
            if any(clean_lower == kw or clean_lower.startswith(f"{kw} ") for kw in ignore_keywords):
                continue
            if any(kw in clean_lower for kw in ["privacy policy", "cookie", "copyright", "terms and conditions", "all rights reserved"]):
                continue
                
            # Must contain a job indicator or the URL must look like a job listing URL
            has_job_indicator = any(ind in clean_lower.split() or f"-{ind}" in clean_lower or f" {ind}" in clean_lower for ind in job_indicators)
            is_job_url = any(p in href_lower for p in ["/job/", "/jobs/", "/vacancy/", "/vacancies/", "/position/", "/role/", "/opening/", "/careers/", "boards.greenhouse", "jobs.lever", "ashbyhq", "workable", "teamtailor"])
            
            if has_job_indicator or is_job_url:
                # Skip javascript or hash links and use careers_url instead
                if href.strip().lower().startswith(("javascript:", "#")):
                    full_url = careers_url
                else:
                    full_url = urllib.parse.urljoin(careers_url, href)
                    
                # Skip external social links
                if any(s in full_url.lower() for s in ["youtube.com", "facebook.com", "twitter.com", "linkedin.com", "instagram.com", "cloudflare.com"]):
                    continue
                    
                job_id = f"html_{company_name}_{clean_title}".lower().replace(' ', '_')
                job_id = re.sub(r'[^a-z0-9_]', '', job_id)
                
                jobs.append({
                    "id": job_id,
                    "title": clean_title,
                    "company": company_name,
                    "location": "",
                    "url": full_url,
                    "department": "",
                    "source": "Direct Web",
                })
                
    return jobs

def extract_jobs_from_company(comp, failed_pages=None, failed_lock=None):
    """
    Routes company to appropriate parser based on ATS or careers URL.
    Captures any timeouts or network errors for manual review.
    """
    careers_url = comp.get("careers_url")
    company_name = comp.get("name", "")
    
    if not careers_url:
        return []
        
    def _record_fail(source, err, url=None):
        if failed_pages is not None:
            status, err_type = classify_fetch_error(err)
            entry = {
                "company": company_name,
                "url": url or careers_url,
                "source": source,
                "status": status,
                "error_type": err_type,
                "detail": str(err),
                "timestamp": datetime.datetime.now().isoformat()
            }
            if failed_lock:
                with failed_lock:
                    failed_pages.append(entry)
            else:
                failed_pages.append(entry)
        
    # Check Greenhouse
    gh_match = re.search(r'greenhouse\.io/([^/?#]+)', careers_url)
    if gh_match:
        try:
            return fetch_greenhouse_jobs(gh_match.group(1), company_name)
        except Exception as e:
            _record_fail("Greenhouse", e, careers_url)
            return []
        
    # Check Lever
    lever_match = re.search(r'jobs\.lever\.co/([^/?#]+)', careers_url)
    if lever_match:
        try:
            return fetch_lever_jobs(lever_match.group(1), company_name)
        except Exception as e:
            _record_fail("Lever", e, careers_url)
            return []
        
    # Check Ashby
    ashby_match = re.search(r'jobs\.ashbyhq\.com/([^/?#]+)', careers_url)
    if ashby_match:
        try:
            return fetch_ashby_jobs(ashby_match.group(1), company_name)
        except Exception as e:
            _record_fail("Ashby", e, careers_url)
            return []

    # Check Workable
    slug = None
    wm_apply = re.search(r'apply\.workable\.com/(?:api/v\d+/widget/accounts/)?([a-zA-Z0-9_\-]+)', careers_url)
    if wm_apply:
        slug = wm_apply.group(1)
    else:
        wm_sub = re.search(r'([a-zA-Z0-9_\-]+)\.workable\.com', careers_url)
        if wm_sub:
            slug = wm_sub.group(1)

    workable_reserved = {"jobs", "j", "api", "widget", "www", "embed", "assets", "resources", "help", "support", "static"}
    if slug and slug.lower() not in workable_reserved:
        try:
            return fetch_workable_jobs(slug, company_name)
        except Exception as e:
            _record_fail("Workable", e, careers_url)
            return []

    # Fallback to HTML parser
    try:
        return fetch_html_career_page_jobs(careers_url, company_name, failed_recorder=_record_fail)
    except Exception as e:
        _record_fail("Direct Web", e, careers_url)
        return []

def is_matching_job(job, search_config):
    """
    Checks if a job listing matches configured search keywords and criteria.
    """
    title = job.get("title", "").lower()
    department = job.get("department", "").lower()
    company = job.get("company", "").lower()
    location = job.get("location", "").lower()
    full_text = f"{title} {department} {company}"
    
    # Check exclude companies
    exclude_companies = [c.lower().strip() for c in search_config.get("exclude_companies", []) if c.strip()]
    if exclude_companies:
        if any(c in company for c in exclude_companies):
            return False
            
    # Check keywords
    keywords = [k.lower().strip() for k in search_config.get("keywords", []) if k.strip()]
    if keywords:
        if not any(k in full_text for k in keywords):
            return False
            
    # Check exclude keywords
    exclude_keywords = [k.lower().strip() for k in search_config.get("exclude_keywords", []) if k.strip()]
    if any(k in full_text for k in exclude_keywords):
        return False
        
    # Check location rules & distance
    if evaluate_location_rules is not None:
        loc_match, _ = evaluate_location_rules(
            job,
            location_rules=search_config.get("location_rules", []),
            legacy_location_filter=search_config.get("location_filter", []),
            legacy_remote_only=search_config.get("remote_only", False)
        )
        if not loc_match:
            return False
    else:
        # Fallback legacy checks
        if search_config.get("remote_only", False):
            if "remote" not in location and "remote" not in title:
                return False
                
        location_filter = [loc.lower().strip() for loc in search_config.get("location_filter", []) if loc.strip()]
        if location_filter:
            loc_text = f"{location} {title}"
            if not any(loc in loc_text for loc in location_filter):
                return False
        
    return True

# --- Notifications ---

def show_standalone_toast(title, message, url=None, duration=8):
    """Displays desktop notification toast."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        w, h = 380, 100
        x = sw - w - 20
        y = sh - h - 50
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.configure(bg="#1e1e2e", highlightbackground="#89b4fa", highlightthickness=1)
        
        lbl_title = tk.Label(root, text=title, font=("Segoe UI", 10, "bold"), fg="#89b4fa", bg="#1e1e2e", anchor="w")
        lbl_title.pack(fill="x", padx=10, pady=(6, 2))
        
        lbl_msg = tk.Label(root, text=message, font=("Segoe UI", 9), fg="#cdd6f4", bg="#1e1e2e", anchor="w", justify="left", wraplength=350)
        lbl_msg.pack(fill="x", padx=10)
        
        if url:
            import webbrowser
            def open_link(e=None):
                webbrowser.open(url)
                root.destroy()
            root.bind("<Button-1>", open_link)
            lbl_title.bind("<Button-1>", open_link)
            lbl_msg.bind("<Button-1>", open_link)
            
        root.after(duration * 1000, root.destroy)
        root.mainloop()
    except Exception as e:
        print(f"[!] Toast notification error: {e}")

def send_discord_notification(webhook_url, jobs):
    if not webhook_url:
        return
    for job in jobs[:10]:
        payload = {
            "embeds": [{
                "title": f"🎨 New Job: {job.get('title')}",
                "description": f"**Studio**: {job.get('company')}\n**Location**: {job.get('location') or 'Not specified'}\n**Source**: {job.get('source', 'Career Page')}",
                "url": job.get("url"),
                "color": 0x89b4fa,
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "footer": {"text": "GamesMap UK Job Monitor"}
            }]
        }
        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
            )
            urllib.request.urlopen(req, timeout=10)
            time.sleep(0.3)
        except Exception as e:
            print(f"[!] Error sending Discord webhook: {e}")

def send_notifications(new_jobs, config):
    notif_cfg = config.get("notifications", {})
    
    # 1. Desktop Toast
    if notif_cfg.get("windows_toast", True) and new_jobs:
        first_job = new_jobs[0]
        title = f"🎨 {len(new_jobs)} New Game Job{'s' if len(new_jobs) > 1 else ''} Found!"
        message = f"{first_job.get('company')}: {first_job.get('title')}"
        if len(new_jobs) > 1:
            message += f"\n+{len(new_jobs)-1} more roles"
        show_standalone_toast(title, message, url=first_job.get("url"))
        
    # 2. Discord Webhook
    discord_url = notif_cfg.get("discord_webhook_url")
    if discord_url:
        send_discord_notification(discord_url, new_jobs)

def scan_all_career_pages(max_workers=8, init_mode=False, dry_run=False):
    """
    Scans all studio career pages in companies.json for new job postings.
    """
    if not os.path.exists(COMPANIES_DB_FILE):
        print(f"[!] Companies database {COMPANIES_DB_FILE} not found. Run gamesmap_scraper.py first.")
        return []
        
    with open(COMPANIES_DB_FILE, "r", encoding="utf-8") as f:
        companies_db = json.load(f)
        
    studios_with_careers = [c for c in companies_db.values() if c.get("careers_url") and c.get("status") != "defunct"]
    print(f"[*] Scanning {len(studios_with_careers)} active game studio career pages for open positions (Workers: {max_workers})...")
    
    config = load_config()
    seen_ids = load_seen_jobs()
    
    all_matched_jobs = []
    total_jobs_found = 0
    failed_pages = []
    failed_lock = threading.Lock()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_comp = {executor.submit(extract_jobs_from_company, comp, failed_pages, failed_lock): comp for comp in studios_with_careers}
        
        completed_count = 0
        total_count = len(studios_with_careers)
        for future in as_completed(future_to_comp):
            comp = future_to_comp[future]
            completed_count += 1
            comp_name = comp.get("name", "Studio")
            pct = (completed_count / total_count) * 100
            sys.stdout.write(f"\r[*] [{completed_count}/{total_count}] ({pct:.0f}%) Querying: {comp_name[:35]:<35} | Matches: {len(all_matched_jobs)}  ")
            sys.stdout.flush()
            try:
                jobs = future.result()
                total_jobs_found += len(jobs)
                for j in jobs:
                    if is_matching_job(j, config.get("search", {})):
                        all_matched_jobs.append(j)
            except Exception as e:
                pass

    # Scan recruiter and job board platforms if enabled
    sources_cfg = config.get("search", {}).get("sources", {})
    if fetch_all_recruiter_jobs is not None:
        recruiter_enabled = any([
            sources_cfg.get("query_aardvark", True),
            sources_cfg.get("query_ingame", True),
            sources_cfg.get("query_gibiz", True),
            sources_cfg.get("query_workwithindies", True),
            sources_cfg.get("query_datascope", True)
        ])
        if recruiter_enabled:
            print("[*] Scanning games recruiter platforms & job boards (Aardvark Swift, InGame, GI.biz, Work With Indies)...")
            rec_jobs = fetch_all_recruiter_jobs(sources_cfg)
            total_jobs_found += len(rec_jobs)
            for j in rec_jobs:
                if is_matching_job(j, config.get("search", {})):
                    all_matched_jobs.append(j)

    # Scan Games Jobs Index if enabled
    if fetch_gamesjobsindex_jobs is not None and sources_cfg.get("query_gamesjobsindex", True):
        print("[*] Scanning Games Jobs Index (15,000+ live game dev roles)...")
        gji_jobs = fetch_gamesjobsindex_jobs(sources_cfg)
        total_jobs_found += len(gji_jobs)
        gji_matches = 0
        for j in gji_jobs:
            if is_matching_job(j, config.get("search", {})):
                all_matched_jobs.append(j)
                gji_matches += 1
        print(f"  [✓] Games Jobs Index: {len(gji_jobs):,} roles checked, {gji_matches} matched filters.")

    print(f"\n[✓] Completed scan: extracted {total_jobs_found:,} total jobs across career pages, recruiter boards & Games Jobs Index.")
    print(f"[✓] Filter matched: {len(all_matched_jobs)} Technical Artist / related roles.")
    
    # Generate structured Tech Artist report
    generate_tech_artist_report(all_matched_jobs)
    
    # Save and output failed/timed-out career pages report
    save_failed_pages_reports(failed_pages)
    
    if failed_pages:
        timeouts = [p for p in failed_pages if p.get("status") == "timeout"]
        throttled = [p for p in failed_pages if p.get("status") == "rate_limited"]
        others = [p for p in failed_pages if p.get("status") not in ("timeout", "rate_limited")]
        print("\n" + "="*70)
        print(f"⚠️  CAREER PAGES WITH TIMEOUTS OR ERRORS ({len(failed_pages)} total):")
        print(f"   (Timeouts: {len(timeouts)}, Throttled/429: {len(throttled)}, Other: {len(others)})")
        print(f"   Saved report for manual checking: failed_job_pages.md")
        print("="*70)
        for p in failed_pages:
            print(f"  🏢 {p['company']} ({p['source']}): {p['error_type']}")
            print(f"     🔗 {p['url']}")
        print("="*70)

        # Trigger automated URL Healer
        try:
            from url_healer import heal_failed_pages
            print("\n[*] Running automated URL Healer (path probing, redirect checks, domain for sale detection)...")
            heal_failed_pages(failed_pages)
        except Exception as he:
            print(f"[!] Warning running URL Healer: {he}")
        print("="*70 + "\n")
    else:
        print("[✓] All studio career pages responded with 0 timeouts or network errors.")
    
    new_jobs = [j for j in all_matched_jobs if j["id"] not in seen_ids]
    
    if init_mode:
        print(f"[*] Initializing database with {len(all_matched_jobs)} existing matching jobs. No notifications sent.")
        for j in all_matched_jobs:
            seen_ids.add(j["id"])
        save_seen_jobs(seen_ids)
        return all_matched_jobs
        
    if new_jobs:
        print("\n" + "="*70)
        print(f"📢 FOUND {len(new_jobs)} NEW JOB OPENING(S):")
        print("="*70)
        for j in new_jobs:
            print(f"  🏢 Studio:   {j.get('company')}")
            print(f"  🎨 Role:     {j.get('title')}")
            print(f"  📍 Location: {j.get('location') or 'Not specified'}")
            print(f"  🔗 Link:     {j.get('url')}")
            print("-" * 70)
            
        if not dry_run:
            send_notifications(new_jobs, config)
            for j in new_jobs:
                seen_ids.add(j["id"])
            save_seen_jobs(seen_ids)
    else:
        print("[*] No new Technical Artist jobs detected since last check.")
        
    return all_matched_jobs

def generate_tech_artist_report(matched_jobs):
    """
    Saves a clean JSON and Markdown report of all currently active Tech Artist positions.
    """
    # 1. Save JSON
    with open(TECH_ART_REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.datetime.now().isoformat(),
            "total_tech_artist_roles": len(matched_jobs),
            "jobs": matched_jobs
        }, f, indent=2, ensure_ascii=False)
        
    # 2. Save Markdown
    lines = [
        "# Technical Artist Roles Across UK Game Studios",
        f"\n*Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n",
        f"Total Roles Discovered: **{len(matched_jobs)}**\n",
        "| Studio | Job Title | Location | Source | Link |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ]
    
    for j in sorted(matched_jobs, key=lambda x: x.get('company', '').lower()):
        comp = j.get('company', 'Unknown')
        title = j.get('title', 'Unknown')
        loc = j.get('location', 'Not specified') or 'Not specified'
        src = j.get('source', 'Web')
        url = j.get('url', '#')
        lines.append(f"| **{comp}** | {title} | {loc} | {src} | [Apply]({url}) |")
        
    with open(TECH_ART_REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Career Page Monitor & Tech Artist Extractor")
    parser.add_argument("--init", action="store_true", help="Seed database with current jobs without sending notifications")
    parser.add_argument("--dry-run", action="store_true", help="Run check without updating seen database")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent workers for scanning career pages")
    parser.add_argument("--test-notify", action="store_true", help="Send a mock test notification to verify channels")
    
    args = parser.parse_args()
    
    if args.test_notify:
        config = load_config()
        mock_job = {
            "id": "mock_test_role_001",
            "title": "Lead Technical Artist (Shaders & Rigging)",
            "company": "Firesprite / Sony Interactive Entertainment",
            "location": "Liverpool, UK (Hybrid)",
            "url": "https://www.firesprite.com/careers/",
            "department": "Technical Art",
            "source": "Career Monitor Test"
        }
        print("[*] Sending mock test notification...")
        send_notifications([mock_job], config)
        print("[OK] Test notification sent.")
        sys.exit(0)
        
    scan_all_career_pages(max_workers=args.workers, init_mode=args.init, dry_run=args.dry_run)
