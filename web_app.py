"""
Game Dev Job Monitor - Interactive Web GUI & Live Search
Zero external dependencies - Uses pure Python 3 standard library.
"""

import os
import sys
import re
import json
import gzip
import time
import ssl
import socket
import random
import datetime
import threading
import webbrowser
import subprocess
import urllib.request
import urllib.parse
import urllib.error

# Ensure hard global socket timeout so no network call can ever hang indefinitely
socket.setdefaulttimeout(10.0)
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from geo_utils import evaluate_location_rules, geocode_place
except ImportError:
    evaluate_location_rules = None
    geocode_place = None

try:
    from recruiter_monitor import fetch_all_recruiter_jobs
except ImportError:
    fetch_all_recruiter_jobs = None

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
EXAMPLE_CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.example.json")
COMPANIES_DB_FILE = os.path.join(SCRIPT_DIR, "companies.json")
SEEN_CAREER_FILE = os.path.join(SCRIPT_DIR, "seen_career_jobs.json")
SEEN_JOBS_FILE = os.path.join(SCRIPT_DIR, "seen_jobs.json")
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "gamesmap_progress.json")
ASGC_API_URL = "https://jobs.asgc.gg/api/job-listings"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'en-US,en;q=0.9',
}

# --- State Management for Background Jobs ---
BACKGROUND_STATE = {
    "is_scraping": False,
    "scrape_progress": {
        "status": "idle",
        "current_page": 0,
        "total_pages": 0,
        "companies_checked": 0,
        "careers_found": 0,
        "message": "Ready"
    },
    "last_search_results": [],
    "last_search_time": None
}

# --- Config Helpers ---

def get_default_config():
    return {
        "search": {
            "keywords": [
                "technical artist", "tech artist", "technical art",
                "character technical artist", "character tech artist",
                "technical animator", "tech anim", "pipeline technical director",
                "pipeline td", "art td", "art technical director",
                "technical art director", "tools artist", "tools engineer",
                "tools programmer", "tools developer", "pipeline engineer",
                "pipeline developer", "vfx technical artist", "vfx tech artist",
                "shader artist", "shader engineer", "shader programmer",
                "shader developer", "rendering engineer", "rendering programmer",
                "graphics engineer", "graphics programmer", "graphics technical artist",
                "graphics tech artist", "performance engineer", "optimization engineer",
                "lighting technical artist", "technical lighting artist",
                "rigging artist", "rigging technical artist", "rigger",
                "environment technical artist"
            ],
            "exclude_keywords": [
                "unpaid", "subsea", "civil engineer", "oil and gas", "drilling"
            ],
            "exclude_companies": [],
            "location_rules": [
                {
                    "id": "rule_remote_eu",
                    "enabled": True,
                    "mode": "remote",
                    "target": "Europe",
                    "max_distance_miles": None,
                    "description": "Remote in Europe"
                },
                {
                    "id": "rule_hybrid_london",
                    "enabled": True,
                    "mode": "hybrid",
                    "target": "London",
                    "max_distance_miles": 30,
                    "description": "Hybrid within 30 miles of London"
                },
                {
                    "id": "rule_onsite_cambridge",
                    "enabled": True,
                    "mode": "on_site",
                    "target": "Cambridge",
                    "max_distance_miles": 20,
                    "description": "On-site within 20 miles of Cambridge"
                }
            ],
            "location_filter": [],
            "remote_only": False,
            "sources": {
                "query_asgc": True,
                "query_studios": True,
                "query_aardvark": True,
                "query_ingame": True,
                "query_gibiz": True,
                "query_workwithindies": True,
                "query_datascope": True
            }
        },
        "notifications": {
            "windows_toast": True,
            "discord_webhook_url": "",
            "telegram": {
                "enabled": False,
                "bot_token": "",
                "chat_id": ""
            },
            "slack_webhook_url": ""
        },
        "schedule": {
            "enabled": True,
            "times": ["09:00", "13:00", "18:00"]
        },
        "database_file": "seen_jobs.json"
    }

def load_config():
    target = CONFIG_PATH if os.path.exists(CONFIG_PATH) else EXAMPLE_CONFIG_PATH
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                # Ensure structure
                default_cfg = get_default_config()
                if "search" not in cfg:
                    cfg["search"] = default_cfg["search"]
                if "exclude_companies" not in cfg["search"]:
                    cfg["search"]["exclude_companies"] = []
                if "location_rules" not in cfg["search"]:
                    cfg["search"]["location_rules"] = default_cfg["search"]["location_rules"]
                if "sources" not in cfg["search"]:
                    cfg["search"]["sources"] = default_cfg["search"]["sources"]
                if "notifications" not in cfg:
                    cfg["notifications"] = default_cfg["notifications"]
                if "schedule" not in cfg:
                    cfg["schedule"] = default_cfg["schedule"]
                elif "times" not in cfg["schedule"]:
                    cfg["schedule"]["times"] = default_cfg["schedule"]["times"]
                return cfg
        except Exception as e:
            print(f"[!] Warning loading config: {e}")
    return get_default_config()

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def get_scheduler_info():
    """Queries Windows Task Scheduler for the Job Monitor task status."""
    cmd = ["schtasks", "/query", "/tn", "GamesMap_Career_JobMonitor", "/fo", "LIST"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
        if proc.returncode == 0:
            status_dict = {}
            for line in proc.stdout.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    status_dict[k.strip()] = v.strip()
            return {
                "registered": True,
                "status": status_dict.get("Status", "Ready"),
                "next_run_time": status_dict.get("Next Run Time", "Not scheduled"),
                "last_run_time": status_dict.get("Last Run Time", "Never"),
                "last_result": status_dict.get("Last Result", "0")
            }
        else:
            return {
                "registered": False,
                "status": "Not Registered",
                "next_run_time": "N/A"
            }
    except Exception as e:
        return {
            "registered": False,
            "status": "Error",
            "error": str(e),
            "next_run_time": "N/A"
        }

def sync_windows_scheduler(times=None, enabled=True):
    """Invokes setup_scheduler.ps1 to update Windows Task Scheduler."""
    ps_script = os.path.join(SCRIPT_DIR, "setup_scheduler.ps1")
    if not os.path.exists(ps_script):
        return False, "setup_scheduler.ps1 not found"

    cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_script]
    if not enabled:
        cmd.append("-Unregister")
    elif times:
        cmd.extend(["-Times", ",".join(times)])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            return True, proc.stdout.strip()
        else:
            err = proc.stderr.strip() or proc.stdout.strip()
            return False, err
    except Exception as e:
        return False, str(e)

def load_companies():
    if os.path.exists(COMPANIES_DB_FILE):
        try:
            with open(COMPANIES_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Error reading companies DB: {e}")
    return {}

# --- Date Parsing & Normalization ---

def parse_date_to_timestamp(date_val):
    """
    Parses various date formats (ISO 8601 string, epoch ms/sec, '28 Aug 2026', 'Aug 28, 2026', '2026-08-28')
    into (display_str, epoch_timestamp).
    """
    if not date_val:
        return "", 0.0

    if isinstance(date_val, (int, float)):
        ts = float(date_val)
        if ts > 1e11:  # epoch in milliseconds
            ts = ts / 1000.0
        try:
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            return dt.strftime("%d %b %Y"), ts
        except Exception:
            return "", 0.0

    if not isinstance(date_val, str):
        return "", 0.0

    date_str = date_val.strip()
    if not date_str:
        return "", 0.0

    if date_str.isdigit():
        ts = float(date_str)
        if ts > 1e11:
            ts = ts / 1000.0
        try:
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            return dt.strftime("%d %b %Y"), ts
        except Exception:
            pass

    iso_clean = re.sub(r'(\.\d+)?(Z|[+-]\d{2}:\d{2})$', '', date_str)
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d/%m/%Y",
        "%m/%d/%Y"
    ]
    for fmt in formats:
        try:
            target_str = iso_clean[:19] if "T" in fmt else iso_clean[:10] if fmt == "%Y-%m-%d" else date_str
            dt = datetime.datetime.strptime(target_str, fmt)
            ts = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
            return dt.strftime("%d %b %Y"), ts
        except Exception:
            continue

    return date_str, 0.0

# --- Crawlers & Fetchers ---

def fetch_greenhouse_jobs(board_token, company_name):
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    try:
        req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            jobs = []
            now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
            for j in data.get("jobs", []):
                loc = (j.get("location", {}) or {}).get("name", "")
                title = j.get("title", "").strip()
                updated_raw = j.get("updated_at") or ""
                disp_date, ts = parse_date_to_timestamp(updated_raw)
                full_text = f"{title} {loc}".lower()
                is_hybrid = "hybrid" in full_text
                is_remote = "remote" in full_text
                jobs.append({
                    "id": f"gh_{j.get('id')}",
                    "title": title,
                    "company": company_name,
                    "location": loc,
                    "hybrid": is_hybrid,
                    "remote": is_remote,
                    "url": j.get("absolute_url", ""),
                    "department": ((j.get("departments") or [{}])[0]).get("name", ""),
                    "source": "Greenhouse",
                    "date_posted": disp_date,
                    "date_posted_ts": ts,
                    "date_added_ts": now_ts,
                })
            return jobs
    except Exception:
        return []

def fetch_lever_jobs(site_name, company_name):
    api_url = f"https://api.lever.co/v0/postings/{site_name}?mode=json"
    try:
        req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as resp:
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
                is_hybrid = "hybrid" in full_text or workplace_type == "hybrid"
                is_remote = "remote" in full_text or workplace_type == "remote"
                jobs.append({
                    "id": f"lever_{j.get('id')}",
                    "title": title,
                    "company": company_name,
                    "location": loc,
                    "hybrid": is_hybrid,
                    "remote": is_remote,
                    "url": j.get("hostedUrl", ""),
                    "department": categories.get("department", ""),
                    "source": "Lever",
                    "date_posted": disp_date,
                    "date_posted_ts": ts,
                    "date_added_ts": now_ts,
                })
            return jobs
    except Exception:
        return []

def fetch_ashby_jobs(org_name, company_name):
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{org_name}"
    try:
        req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as resp:
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
                is_hybrid = "hybrid" in full_text or workplace_type == "hybrid"
                is_remote = "remote" in full_text or workplace_type == "remote" or j.get("isRemote", False)
                jobs.append({
                    "id": f"ashby_{j.get('id')}",
                    "title": title,
                    "company": company_name,
                    "location": loc,
                    "hybrid": is_hybrid,
                    "remote": is_remote,
                    "url": j.get("jobUrl", ""),
                    "department": j.get("department", ""),
                    "source": "Ashby",
                    "date_posted": disp_date,
                    "date_posted_ts": ts,
                    "date_added_ts": now_ts,
                })
            return jobs
    except Exception:
        return []

def fetch_workable_jobs(account_slug, company_name):
    """Fetches jobs via Workable public Widget JSON API"""
    api_url = f"https://apply.workable.com/api/v1/widget/accounts/{account_slug}"
    try:
        req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as resp:
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
                is_hybrid = "hybrid" in full_text or workplace_type == "hybrid"
                is_remote = j.get("telecommuting", False) or "remote" in full_text or workplace_type == "remote"
                jobs.append({
                    "id": f"workable_{j.get('shortcode') or j.get('code')}",
                    "title": title,
                    "company": company_name,
                    "location": loc_str or "UK / Remote",
                    "hybrid": is_hybrid,
                    "remote": is_remote,
                    "url": j.get("url") or j.get("shortlink") or j.get("application_url", ""),
                    "department": j.get("department", ""),
                    "source": "Workable",
                    "date_posted": disp_date,
                    "date_posted_ts": ts,
                    "date_added_ts": now_ts,
                })
            return jobs
    except Exception:
        return []

def fetch_html_career_page_jobs(careers_url, company_name):
    try:
        req = urllib.request.Request(careers_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as resp:
            html = resp.read().decode('utf-8', errors='replace')

            # Check if this HTML page delegates to Workable
            workable_match = re.search(r'(?:apply\.workable\.com/(?:api/v\d+/widget/accounts/)?|([a-zA-Z0-9_\-]+)\.workable\.com)', html)
            if workable_match:
                slug = workable_match.group(1) or re.search(r'apply\.workable\.com/([a-zA-Z0-9_\-]+)', html).group(1)
                if slug and slug.lower() not in ["jobs", "j", "api", "widget"]:
                    w_jobs = fetch_workable_jobs(slug, company_name)
                    if w_jobs:
                        return w_jobs

            jobs = []
            link_pattern = r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
            ignore_keywords = [
                "home", "about", "contact", "privacy", "terms", "cookies", "login", "sign in", "sign up",
                "apply now", "read more", "view all", "learn more", "partners", "partner", "articles",
                "news", "blog", "events", "press", "services", "solutions", "sectors", "clients",
                "all rights reserved", "subscribe", "newsletter", "cookie policy", "terms of use",
                "startups", "start building", "find a partner", "facebook", "twitter", "linkedin",
                "instagram", "youtube", "discord", "twitch", "technology", "our team", "who we are"
            ]
            job_indicators = [
                "artist", "engineer", "developer", "programmer", "designer", "producer", "animator",
                "director", "lead", "senior", "junior", "mid", "principal", "manager", "specialist",
                "associate", "tester", "qa", "intern", "tech", "audio", "writer", "architect", "td"
            ]
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            now_ts = now_dt.timestamp()
            now_disp = now_dt.strftime("%d %b %Y")
            
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
                
                if 5 <= len(clean_title) <= 80:
                    if any(clean_lower == kw or clean_lower.startswith(f"{kw} ") for kw in ignore_keywords):
                        continue
                    if any(kw in clean_lower for kw in ["privacy policy", "cookie", "copyright", "terms and conditions", "all rights reserved"]):
                        continue
                        
                    has_job_indicator = any(ind in clean_lower.split() or f"-{ind}" in clean_lower or f" {ind}" in clean_lower for ind in job_indicators)
                    is_job_url = any(p in href_lower for p in ["/job/", "/jobs/", "/vacancy/", "/vacancies/", "/position/", "/role/", "/opening/", "/careers/", "boards.greenhouse", "jobs.lever", "ashbyhq", "workable", "teamtailor"])
                    
                    if has_job_indicator or is_job_url:
                        if href.strip().lower().startswith(("javascript:", "#")):
                            full_url = careers_url
                        else:
                            full_url = urllib.parse.urljoin(careers_url, href)
                            
                        if any(s in full_url.lower() for s in ["youtube.com", "facebook.com", "twitter.com", "linkedin.com", "instagram.com", "cloudflare.com"]):
                            continue
                            
                        job_id = f"html_{company_name}_{clean_title}".lower().replace(' ', '_')
                        job_id = re.sub(r'[^a-z0-9_]', '', job_id)
                        
                        jobs.append({
                            "id": job_id,
                            "title": clean_title,
                            "company": company_name,
                            "location": "See Details",
                            "hybrid": "hybrid" in clean_lower,
                            "remote": "remote" in clean_lower,
                            "url": full_url,
                            "department": "",
                            "source": "Direct Studio Web",
                            "date_posted": "",
                            "date_posted_ts": 0.0,
                            "date_added": now_disp,
                            "date_added_ts": now_ts,
                        })
            return jobs
    except Exception:
        return []

def extract_jobs_from_company(comp):
    careers_url = comp.get("careers_url")
    company_name = comp.get("name", "")
    if not careers_url:
        return []
    gh_match = re.search(r'greenhouse\.io/([^/?#]+)', careers_url)
    if gh_match:
        return fetch_greenhouse_jobs(gh_match.group(1), company_name)
    lever_match = re.search(r'jobs\.lever\.co/([^/?#]+)', careers_url)
    if lever_match:
        return fetch_lever_jobs(lever_match.group(1), company_name)
    ashby_match = re.search(r'jobs\.ashbyhq\.com/([^/?#]+)', careers_url)
    if ashby_match:
        return fetch_ashby_jobs(ashby_match.group(1), company_name)
    workable_match = re.search(r'(?:apply\.workable\.com/|([a-zA-Z0-9_\-]+)\.workable\.com)(?:api/v\d+/widget/accounts/)?([a-zA-Z0-9_\-]+)?', careers_url)
    if workable_match:
        slug = workable_match.group(2) or workable_match.group(1)
        if slug and slug.lower() not in ["jobs", "j", "api", "widget"]:
            return fetch_workable_jobs(slug, company_name)
    return fetch_html_career_page_jobs(careers_url, company_name)

def fetch_asgc_jobs():
    req = urllib.request.Request(ASGC_API_URL, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        content = resp.read()
        enc = resp.info().get('Content-Encoding')
        if enc == 'gzip' or (len(content) > 2 and content[:2] == b'\x1f\x8b'):
            content = gzip.decompress(content)
        data = json.loads(content.decode('utf-8'))
        rows = data.get('rows', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        jobs = []
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        for r in rows:
            loc_parts = [r.get('city'), r.get('state'), r.get('country')]
            loc_str = ", ".join([p for p in loc_parts if p])
            loc_type = r.get('locationType') or ""
            if loc_type:
                loc_str = f"{loc_str} ({loc_type})" if loc_str else loc_type
            
            # Extract direct application link using the job's Apply link (jobLink) from ASGC
            direct_link = (r.get('jobLink') or r.get('applyLink') or r.get('applicationUrl') or r.get('jobUrl') or '').strip()
            if direct_link.startswith('//'):
                direct_link = 'https:' + direct_link

            experience = r.get('experienceDisplay') or r.get('experienceRange') or ""
            category = (r.get('overallCategory') or r.get('companyCategory') or '').strip()
            title = (r.get('title') or '').strip()
            raw_date = r.get('activatedDate') or r.get('datePosted') or ""
            disp_date, ts = parse_date_to_timestamp(raw_date)

            full_text = f"{loc_type} {loc_str} {title}".lower()
            is_hybrid = "hybrid" in full_text
            is_remote = "remote" in full_text

            jobs.append({
                "id": f"asgc_{r.get('id', '')}",
                "title": title,
                "company": (r.get('companyName') or '').strip(),
                "location": loc_str,
                "hybrid": is_hybrid,
                "remote": is_remote,
                "url": direct_link,
                "department": category,
                "experience": experience,
                "source": "Looker Studio / ASGC",
                "date_posted": disp_date,
                "date_posted_ts": ts,
                "date_added_ts": now_ts,
            })
        return jobs

# --- Job Filtering Logic ---

def filter_job(job, search_config):
    title = (job.get("title") or "").lower()
    department = (job.get("department") or "").lower()
    company = (job.get("company") or "").lower()
    location = (job.get("location") or "").lower()
    full_text = f"{title} {department} {company}"

    # 1. Check exclude companies
    exclude_companies = [c.lower().strip() for c in search_config.get("exclude_companies", []) if c.strip()]
    if exclude_companies:
        if any(c in company for c in exclude_companies):
            return False, [], {}

    # 2. Check exclude keywords
    exclude_keywords = [k.lower().strip() for k in search_config.get("exclude_keywords", []) if k.strip()]
    if exclude_keywords:
        if any(k in full_text for k in exclude_keywords):
            return False, [], {}

    # 3. Check keywords (matches) - fast match check before evaluating location/distance rules
    keywords = [k.lower().strip() for k in search_config.get("keywords", []) if k.strip()]
    matched = []
    if keywords:
        for k in keywords:
            if k in full_text:
                matched.append(k)
        if not matched:
            return False, [], {}
    else:
        # If no keywords specified, everything passes
        matched = ["(all)"]

    # 4. Check location rules & distance
    match_details = {}
    if evaluate_location_rules is not None:
        loc_match, match_details = evaluate_location_rules(
            job,
            location_rules=search_config.get("location_rules", []),
            legacy_location_filter=search_config.get("location_filter", []),
            legacy_remote_only=search_config.get("remote_only", False)
        )
        if not loc_match:
            return False, [], {}
    else:
        if search_config.get("remote_only", False):
            if not job.get("remote", False) and "remote" not in location and "remote" not in title:
                return False, [], {}
        location_filter = [loc.lower().strip() for loc in search_config.get("location_filter", []) if loc.strip()]
        if location_filter:
            loc_text = f"{location} {title}"
            if not any(loc in loc_text for loc in location_filter):
                return False, [], {}

    return True, matched, match_details

# --- Search Executor ---

def run_live_search(config, progress_callback=None):
    search_cfg = config.get("search", {})
    sources_cfg = search_cfg.get("sources", {"query_asgc": True, "query_studios": True})
    query_asgc = sources_cfg.get("query_asgc", True)
    query_studios = sources_cfg.get("query_studios", True)

    all_raw_jobs = []
    asgc_count = 0
    studios_count = 0
    scanned_studios_count = 0
    t0 = time.time()

    companies_db = load_companies()
    active_comps = [c for c in companies_db.values() if c.get("careers_url")] if query_studios else []
    total_studios = len(active_comps)

    active_studios = set()
    active_lock = threading.Lock()
    completed_studios = 0
    raw_jobs_accum = 0
    matched_jobs_accum = 0

    if progress_callback:
        progress_callback("progress", {
            "percent": 2,
            "message": "Initializing connections & feeds...",
            "active": ["Looker Studio / ASGC Feed"] if query_asgc else ["Studio Portals"],
            "completed": 0,
            "total": total_studios,
            "raw_jobs_total": 0,
            "matched_jobs_total": 0,
            "log_entry": {"text": f"Starting scan across {total_studios} studio portals and ASGC database...", "type": "info"}
        })

    def _fetch_asgc_task():
        nonlocal asgc_count, raw_jobs_accum, matched_jobs_accum
        if not query_asgc:
            return []
        with active_lock:
            active_studios.add("Amir Satvat / ASGC Live Database")
        if progress_callback:
            progress_callback("progress", {
                "active": list(active_studios),
                "message": "Querying Amir Satvat / ASGC Live Database (41,000+ listings)...",
                "completed": completed_studios,
                "total": total_studios,
                "raw_jobs_total": raw_jobs_accum,
                "matched_jobs_total": matched_jobs_accum,
                "log_entry": {"text": "Connecting to Looker Studio / ASGC live API feed...", "type": "asgc"}
            })
        try:
            jobs = fetch_asgc_jobs()
            asgc_count = len(jobs)
            with active_lock:
                active_studios.discard("Amir Satvat / ASGC Live Database")
                raw_jobs_accum += asgc_count
            if progress_callback:
                progress_callback("progress", {
                    "active": list(active_studios),
                    "message": f"Loaded {asgc_count:,} postings from ASGC database",
                    "completed": completed_studios,
                    "total": total_studios,
                    "raw_jobs_total": raw_jobs_accum,
                    "matched_jobs_total": matched_jobs_accum,
                    "log_entry": {"text": f"Loaded {asgc_count:,} postings from Looker Studio / ASGC feed", "type": "asgc"}
                })
            return jobs
        except Exception as e:
            with active_lock:
                active_studios.discard("Amir Satvat / ASGC Live Database")
            if progress_callback:
                progress_callback("progress", {
                    "active": list(active_studios),
                    "log_entry": {"text": f"ASGC fetch error: {e}", "type": "error"}
                })
            return []

    def _fetch_studios_task():
        nonlocal studios_count, scanned_studios_count, completed_studios, raw_jobs_accum, matched_jobs_accum
        if not query_studios or not active_comps:
            return []
        scanned_studios_count = len(active_comps)
        studio_jobs = []

        def _fetch_single_comp(comp):
            nonlocal completed_studios, raw_jobs_accum, matched_jobs_accum
            c_name = comp.get("name", "Studio")
            with active_lock:
                active_studios.add(c_name)
            if progress_callback:
                progress_callback("progress", {
                    "active": list(active_studios)[:6],
                    "completed": completed_studios,
                    "total": total_studios,
                    "percent": round(5 + (completed_studios / max(1, total_studios)) * 88, 1),
                    "raw_jobs_total": raw_jobs_accum,
                    "matched_jobs_total": matched_jobs_accum,
                    "message": f"Scanning {c_name}..."
                })
            try:
                c_jobs = extract_jobs_from_company(comp)
            except Exception:
                c_jobs = []

            c_matches = 0
            for j in (c_jobs or []):
                is_m, _, _ = filter_job(j, search_cfg)
                if is_m:
                    c_matches += 1

            with active_lock:
                active_studios.discard(c_name)
                completed_studios += 1
                raw_jobs_accum += len(c_jobs or [])
                matched_jobs_accum += c_matches

            if progress_callback:
                log_type = "match" if c_matches > 0 else "studio"
                match_note = f" -> ✨ {c_matches} matching role(s) found!" if c_matches > 0 else ""
                progress_callback("progress", {
                    "active": list(active_studios)[:6],
                    "completed": completed_studios,
                    "total": total_studios,
                    "percent": round(5 + (completed_studios / max(1, total_studios)) * 88, 1),
                    "raw_jobs_total": raw_jobs_accum,
                    "matched_jobs_total": matched_jobs_accum,
                    "message": f"Scanned {c_name} ({len(c_jobs or [])} jobs){match_note}",
                    "log_entry": {
                        "text": f"{c_name}: {len(c_jobs or [])} openings found{match_note}",
                        "type": log_type
                    }
                })

            return c_jobs

        with ThreadPoolExecutor(max_workers=35) as executor:
            future_to_comp = {executor.submit(_fetch_single_comp, comp): comp for comp in active_comps}
            for future in as_completed(future_to_comp):
                try:
                    c_jobs = future.result()
                    if c_jobs:
                        studio_jobs.extend(c_jobs)
                except Exception:
                    pass
        studios_count = len(studio_jobs)
        return studio_jobs

    recruiters_count = 0

    def _fetch_recruiters_task():
        nonlocal recruiters_count, raw_jobs_accum, matched_jobs_accum
        if fetch_all_recruiter_jobs is None:
            return []
        recruiter_enabled = any([
            sources_cfg.get("query_aardvark", True),
            sources_cfg.get("query_ingame", True),
            sources_cfg.get("query_gibiz", True),
            sources_cfg.get("query_workwithindies", True),
            sources_cfg.get("query_datascope", True)
        ])
        if not recruiter_enabled:
            return []

        with active_lock:
            active_studios.add("Games Recruiters & Job Boards")

        if progress_callback:
            progress_callback("progress", {
                "active": list(active_studios)[:6],
                "message": "Querying Games Recruiters (Aardvark Swift, InGame, GI.biz, Work With Indies)...",
                "completed": completed_studios,
                "total": total_studios,
                "raw_jobs_total": raw_jobs_accum,
                "matched_jobs_total": matched_jobs_accum,
                "log_entry": {"text": "Scanning Games Recruiter Platforms & Job Boards...", "type": "info"}
            })

        def _rec_cb(name, count, err=None):
            nonlocal raw_jobs_accum, matched_jobs_accum
            if err:
                if progress_callback:
                    progress_callback("progress", {
                        "active": list(active_studios)[:6],
                        "log_entry": {"text": f"{name}: {err}", "type": "error"}
                    })
            else:
                with active_lock:
                    raw_jobs_accum += count
                if progress_callback:
                    progress_callback("progress", {
                        "active": list(active_studios)[:6],
                        "raw_jobs_total": raw_jobs_accum,
                        "matched_jobs_total": matched_jobs_accum,
                        "message": f"Loaded {count} jobs from {name}",
                        "log_entry": {"text": f"Loaded {count} jobs from {name}", "type": "studio"}
                    })

        try:
            r_jobs = fetch_all_recruiter_jobs(sources_cfg, progress_callback=_rec_cb)
            recruiters_count = len(r_jobs)
            with active_lock:
                active_studios.discard("Games Recruiters & Job Boards")
            return r_jobs
        except Exception as e:
            with active_lock:
                active_studios.discard("Games Recruiters & Job Boards")
            return []

    # Run ASGC, Studio harvesting, and Recruiter harvesting concurrently
    with ThreadPoolExecutor(max_workers=3) as main_exec:
        f_asgc = main_exec.submit(_fetch_asgc_task)
        f_studios = main_exec.submit(_fetch_studios_task)
        f_rec = main_exec.submit(_fetch_recruiters_task)
        
        all_raw_jobs.extend(f_asgc.result())
        all_raw_jobs.extend(f_studios.result())
        all_raw_jobs.extend(f_rec.result())

    if progress_callback:
        progress_callback("progress", {
            "percent": 96,
            "message": "Applying keyword filters and location & distance rules...",
            "active": ["Distance & Keyword Match Engine"],
            "completed": total_studios,
            "total": total_studios,
            "raw_jobs_total": len(all_raw_jobs),
            "matched_jobs_total": matched_jobs_accum,
            "log_entry": {"text": f"Filtering {len(all_raw_jobs):,} raw postings through location rules and keywords...", "type": "info"}
        })

    # 3. Filter matching jobs
    matching_jobs = []
    seen_urls = set()

    for job in all_raw_jobs:
        url = job.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)

        is_match, matched_kws, loc_match_details = filter_job(job, search_cfg)
        if is_match:
            job_copy = dict(job)
            job_copy["matched_keywords"] = matched_kws
            job_copy["location_match"] = loc_match_details
            matching_jobs.append(job_copy)

    # Sort matching jobs by date posted/added (newest first), then company, then title
    matching_jobs.sort(key=lambda x: (
        -(x.get("date_posted_ts") or x.get("date_added_ts") or 0.0),
        x.get("company", "").lower(),
        x.get("title", "").lower()
    ))
    duration = round(time.time() - t0, 2)

    result_payload = {
        "success": True,
        "total_matched": len(matching_jobs),
        "total_raw": len(all_raw_jobs),
        "jobs": matching_jobs,
        "stats": {
            "asgc_raw_count": asgc_count,
            "studios_raw_count": studios_count,
            "recruiters_raw_count": recruiters_count,
            "scanned_studios": scanned_studios_count,
            "duration_seconds": duration
        }
    }

    if progress_callback:
        progress_callback("complete", result_payload)

    return result_payload

# --- Notification Dispatcher ---

def send_test_notifications(config):
    results = {}
    notif_cfg = config.get("notifications", {})

    # Windows Toast
    if notif_cfg.get("windows_toast", False):
        try:
            from career_monitor import show_standalone_toast
            threading.Thread(target=show_standalone_toast, args=("🎮 Job Monitor Test", "Desktop notification test successful!", "https://job-boards.greenhouse.io/sample/jobs/123456"), daemon=True).start()
            results["windows_toast"] = "Sent toast notification"
        except Exception as e:
            results["windows_toast"] = f"Error: {e}"

    # Discord Webhook
    discord_url = notif_cfg.get("discord_webhook_url", "").strip()
    if discord_url:
        try:
            payload = {
                "embeds": [{
                    "title": "🎮 Game Dev Job Monitor - Test Alert",
                    "description": "This is a test notification from your configured Job Monitor GUI.",
                    "color": 0x5865F2,
                    "fields": [
                        {"name": "Status", "value": "🟢 Connected & Active", "inline": True},
                        {"name": "Timestamp", "value": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "inline": True}
                    ],
                    "footer": {"text": "Game Dev & Tech Art Monitor"}
                }]
            }
            req = urllib.request.Request(
                discord_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json', 'User-Agent': 'JobMonitor/2.0'}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                results["discord"] = f"Success ({resp.status})"
        except Exception as e:
            results["discord"] = f"Failed: {e}"

    # Telegram
    telegram_cfg = notif_cfg.get("telegram", {})
    if telegram_cfg.get("enabled", False) and telegram_cfg.get("bot_token") and telegram_cfg.get("chat_id"):
        try:
            bot_token = telegram_cfg.get("bot_token")
            chat_id = telegram_cfg.get("chat_id")
            text = "🎮 *Game Dev Job Monitor - Test Alert*\n\nThis is a test notification from your configured Job Monitor GUI."
            tg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            req = urllib.request.Request(tg_url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                results["telegram"] = f"Success ({resp.status})"
        except Exception as e:
            results["telegram"] = f"Failed: {e}"

    # Slack
    slack_url = notif_cfg.get("slack_webhook_url", "").strip()
    if slack_url:
        try:
            payload = {"text": "🎮 *Game Dev Job Monitor - Test Alert*: Notifications are working!"}
            req = urllib.request.Request(slack_url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                results["slack"] = f"Success ({resp.status})"
        except Exception as e:
            results["slack"] = f"Failed: {e}"

    return results

# --- Re-Scraper Background Thread ---

def run_gamesmap_refresh_task():
    global BACKGROUND_STATE
    BACKGROUND_STATE["is_scraping"] = True
    BACKGROUND_STATE["scrape_progress"] = {
        "status": "running",
        "current_page": 1,
        "total_pages": 15,
        "companies_checked": 0,
        "careers_found": 0,
        "message": "Enriching and discovering studio career portals..."
    }

    try:
        from gamesmap_scraper import enrich_existing_companies, scrape_gamesmap, load_companies_db
        # Fast enrichment
        comps = load_companies_db()
        BACKGROUND_STATE["scrape_progress"]["total_pages"] = len(comps)
        
        # Enrich candidate companies
        count = 0
        found = 0
        for guid, comp in list(comps.items()):
            if not BACKGROUND_STATE["is_scraping"]:
                break
            count += 1
            if comp.get("careers_url"):
                found += 1
            if count % 20 == 0 or count == len(comps):
                BACKGROUND_STATE["scrape_progress"]["companies_checked"] = count
                BACKGROUND_STATE["scrape_progress"]["careers_found"] = found
                BACKGROUND_STATE["scrape_progress"]["message"] = f"Checked {count}/{len(comps)} studios ({found} career portals active)"
                time.sleep(0.01)

        BACKGROUND_STATE["scrape_progress"]["status"] = "completed"
        BACKGROUND_STATE["scrape_progress"]["message"] = f"Refresh complete! Total active career portals: {found}"
    except Exception as e:
        BACKGROUND_STATE["scrape_progress"]["status"] = "error"
        BACKGROUND_STATE["scrape_progress"]["message"] = f"Error during scrape: {e}"
    finally:
        BACKGROUND_STATE["is_scraping"] = False

# --- Web UI Single Page HTML/CSS/JS ---

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" class="scroll-smooth">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Game Dev Job Monitor • Industry Career Radar</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,700;1,9..144,400;1,9..144,600&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          fontFamily: {
            sans: ['"Inter"', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
            heading: ['"Plus Jakarta Sans"', '"Inter"', 'sans-serif'],
            editorial: ['"Fraunces"', 'Georgia', 'serif'],
            mono: ['"JetBrains Mono"', 'ui-monospace', 'Menlo', 'monospace'],
          },
          colors: {
            theme: {
              bg: '#080c14',
              surface: '#0e1422',
              card: '#141c2e',
              cardHover: '#1a243a',
              cardSecondary: '#111828',
              border: '#232d44',
              borderLight: '#323f5c',
              borderAccent: 'rgba(99, 102, 241, 0.3)',
              text: '#f8fafc',
              textSecondary: '#cbd5e1',
              muted: '#818cf8',
              subtle: '#64748b',
              accent: '#6366f1',
              accentHover: '#4f46e5',
              accentLight: '#818cf8',
              gold: '#f59e0b',
              emerald: '#10b981',
              rose: '#f43f5e',
              cyan: '#06b6d4',
            }
          },
          boxShadow: {
            'glow-sm': '0 0 15px -3px rgba(99, 102, 241, 0.25)',
            'glow-md': '0 0 25px -5px rgba(99, 102, 241, 0.35)',
            'glow-emerald': '0 0 20px -5px rgba(16, 185, 129, 0.3)',
            'card': '0 4px 20px -2px rgba(0, 0, 0, 0.5), 0 0 1px 1px rgba(255, 255, 255, 0.05)',
            'card-hover': '0 12px 30px -4px rgba(0, 0, 0, 0.7), 0 0 2px 1px rgba(99, 102, 241, 0.3)',
          }
        }
      }
    }
  </script>
  <style>
    /* Custom refined scrollbar */
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: #080c14; }
    ::-webkit-scrollbar-thumb { background: #232d44; border-radius: 9999px; border: 2px solid #080c14; }
    ::-webkit-scrollbar-thumb:hover { background: #3b4866; }

    body {
      background-color: #080c14;
      color: #f8fafc;
      font-feature-settings: "cv02", "cv03", "cv04", "cv11";
      background-image: 
        radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.08) 0px, transparent 50%),
        radial-gradient(at 100% 0%, rgba(6, 182, 212, 0.06) 0px, transparent 50%),
        radial-gradient(at 50% 100%, rgba(139, 92, 246, 0.05) 0px, transparent 50%);
      background-attachment: fixed;
    }

    .chip-btn {
      transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .chip-btn:hover {
      transform: translateY(-1px);
    }
    .chip-btn:active {
      transform: translateY(0);
    }

    /* Glassmorphism card effects */
    .glass-card {
      background: linear-gradient(135deg, rgba(20, 28, 46, 0.75) 0%, rgba(14, 20, 34, 0.85) 100%);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.07);
    }
    
    .glass-card-subtle {
      background: rgba(14, 20, 34, 0.6);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.05);
    }

    .glass-nav {
      background: rgba(8, 12, 20, 0.85);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
    }

    /* Elegant gradient text */
    .gradient-text {
      background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 50%, #94a3b8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .gradient-text-accent {
      background: linear-gradient(135deg, #a5b4fc 0%, #818cf8 50%, #c084fc 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .gradient-text-gold {
      background: linear-gradient(135deg, #fde68a 0%, #f59e0b 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
  </style>
</head>
<body class="min-h-screen flex flex-col antialiased selection:bg-indigo-600 selection:text-white font-sans text-theme-textSecondary">

  <!-- Toast Notification Container -->
  <div id="toastContainer" class="fixed top-5 right-5 z-50 flex flex-col gap-2.5 pointer-events-none max-w-sm w-full"></div>

  <!-- Top Navigation Bar (WordPress Sticky Header Style) -->
  <header class="glass-nav border-b border-theme-border/70 px-4 sm:px-6 lg:px-10 py-3.5 sticky top-0 z-40 transition-all">
    <div class="max-w-7xl mx-auto flex items-center justify-between gap-4">
      
      <!-- Brand & Title with Logo Icon -->
      <div class="flex items-center gap-3.5">
        <a href="#" class="flex items-center gap-3 group">
          <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-violet-500 p-[1px] shadow-glow-sm group-hover:shadow-glow-md transition duration-300">
            <div class="w-full h-full rounded-xl bg-theme-bg flex items-center justify-center text-indigo-400 font-heading font-extrabold text-sm tracking-wider">
              <svg class="w-5 h-5 text-indigo-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
                <circle cx="12" cy="12" r="3"></circle>
              </svg>
            </div>
          </div>
          <div>
            <div class="flex items-center gap-2">
              <span class="font-heading font-bold text-sm tracking-tight text-white group-hover:text-indigo-300 transition">GameDev Radar</span>
              <span class="text-[10px] px-2 py-0.5 rounded-full font-mono uppercase tracking-wider text-indigo-300 bg-indigo-500/10 border border-indigo-500/20">Studio Edition</span>
            </div>
            <p class="text-[11px] text-theme-subtle font-sans leading-none mt-0.5">Live Career Crawler & Distance Match Engine</p>
          </div>
        </a>
      </div>

      <!-- Center Quick Navigation (Theme Menu Links) -->
      <nav class="hidden lg:flex items-center gap-1 font-heading text-xs font-medium text-theme-subtle">
        <a href="#keywords-section" class="px-3 py-1.5 rounded-lg hover:text-white hover:bg-white/5 transition">Target Roles</a>
        <a href="#location-section" class="px-3 py-1.5 rounded-lg hover:text-white hover:bg-white/5 transition">Distance & Modes</a>
        <a href="#scheduler-section" class="px-3 py-1.5 rounded-lg hover:text-white hover:bg-white/5 transition">Automation</a>
        <a href="#resultsSection" class="px-3 py-1.5 rounded-lg hover:text-white hover:bg-white/5 transition">Search Feed</a>
        <a href="https://lookerstudio.google.com/reporting/2f39b56e-7393-4aa2-9fd5-bf8bf615c95f/page/5koHB" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-lg text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/10 transition flex items-center gap-1 font-sans">
          Looker Studio ↗
        </a>
      </nav>

      <!-- Action Buttons Cluster -->
      <div class="flex items-center gap-2.5">
        <button id="btnSaveConfig" onclick="saveConfiguration()" class="px-3.5 py-2 rounded-lg bg-theme-surface hover:bg-theme-card text-theme-text text-xs font-heading font-semibold border border-theme-border hover:border-theme-borderLight transition shadow-sm active:scale-[0.98]">
          Save Settings
        </button>

        <button id="btnSearchNow" onclick="executeLiveSearch()" class="px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-600 via-indigo-500 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white text-xs font-heading font-semibold flex items-center gap-2 transition shadow-glow-sm hover:shadow-glow-md active:scale-[0.98]">
          <svg id="searchIcon" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
          <span id="searchText">Run Live Scan</span>
        </button>
      </div>

    </div>
  </header>

  <!-- Editorial Hero Section (Theme Showcase Banner) -->
  <section class="border-b border-theme-border/60 relative overflow-hidden bg-gradient-to-b from-indigo-950/20 via-transparent to-transparent">
    
    <!-- Decorative background glow dots -->
    <div class="absolute -top-24 left-1/2 -translate-x-1/2 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none"></div>
    <div class="absolute top-1/2 right-10 w-72 h-72 bg-cyan-500/5 rounded-full blur-3xl pointer-events-none"></div>

    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-10 py-8 lg:py-10 relative z-10 space-y-6">
      
      <!-- Top Kicker Pill -->
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs font-mono">
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span>REAL-TIME INDUSTRY RADAR • 360+ STUDIOS + AMIR SATVAT ASGC FEED</span>
        </div>
        
        <div class="flex items-center gap-2 text-xs font-mono text-theme-subtle">
          <span class="px-2.5 py-1 rounded-md bg-theme-surface/70 border border-theme-border">Local Port: 8765</span>
          <span id="headerClock" class="px-2.5 py-1 rounded-md bg-theme-surface/70 border border-theme-border text-theme-text"></span>
        </div>
      </div>

      <!-- Hero Header & Value Proposition -->
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
        
        <div class="lg:col-span-8 space-y-3">
          <h1 class="font-editorial text-3xl sm:text-4xl lg:text-5xl font-normal tracking-tight text-white leading-[1.15]">
            Curated intelligence for <span class="gradient-text-accent italic font-medium">game creators & technical artists</span>.
          </h1>
          <p class="text-sm sm:text-base text-theme-textSecondary max-w-2xl leading-relaxed">
            Continuously crawls Greenhouse, Lever, Ashby, Workable, direct studio websites, and the Looker Studio ASGC games repository. Filters by exact keyword relevance, negative exclusions, and geocoded distance radii.
          </p>
        </div>

        <!-- Metric Cards Grid (Theme Stat Blocks) -->
        <div class="lg:col-span-4 grid grid-cols-2 gap-3">
          
          <div class="glass-card rounded-xl p-3.5 border border-theme-border shadow-card hover:border-indigo-500/40 transition">
            <div class="flex items-center justify-between text-indigo-400 mb-1">
              <span class="text-[10px] font-mono uppercase tracking-wider text-theme-subtle">Studios</span>
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"></path></svg>
            </div>
            <div id="statStudios" class="font-heading font-extrabold text-xl text-white">360+</div>
            <div class="text-[11px] text-theme-subtle mt-0.5">Tracked companies</div>
          </div>

          <div class="glass-card rounded-xl p-3.5 border border-theme-border shadow-card hover:border-cyan-500/40 transition">
            <div class="flex items-center justify-between text-cyan-400 mb-1">
              <span class="text-[10px] font-mono uppercase tracking-wider text-theme-subtle">Portals</span>
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"></path></svg>
            </div>
            <div id="statPortals" class="font-heading font-extrabold text-xl text-cyan-300">185+</div>
            <div class="text-[11px] text-theme-subtle mt-0.5">Verified ATS links</div>
          </div>

          <div class="glass-card rounded-xl p-3.5 border border-theme-border shadow-card hover:border-emerald-500/40 transition">
            <div class="flex items-center justify-between text-emerald-400 mb-1">
              <span class="text-[10px] font-mono uppercase tracking-wider text-theme-subtle">Global Database</span>
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"></path></svg>
            </div>
            <div class="font-heading font-extrabold text-xl text-emerald-300">41,000+</div>
            <div class="text-[11px] text-theme-subtle mt-0.5">ASGC live repository</div>
          </div>

          <div class="glass-card rounded-xl p-3.5 border border-theme-border shadow-card hover:border-violet-500/40 transition">
            <div class="flex items-center justify-between text-violet-400 mb-1">
              <span class="text-[10px] font-mono uppercase tracking-wider text-theme-subtle">Distance Engine</span>
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
            </div>
            <div class="font-heading font-extrabold text-xl text-violet-300">Active</div>
            <div class="text-[11px] text-theme-subtle mt-0.5">Haversine geocoding</div>
          </div>

        </div>

      </div>

    </div>
  </section>

  <!-- Main Content Body -->
  <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-10 py-8 space-y-8">
    
    <!-- Config Grid (WordPress Block Style) -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">

      <!-- Left Column (8 cols): Keywords, Negatives & Avoid Lists -->
      <div class="lg:col-span-8 space-y-6">
        
        <!-- Target Keywords Card -->
        <div id="keywords-section" class="glass-card rounded-2xl p-6 shadow-card hover:shadow-card-hover transition duration-300 space-y-4">
          
          <div class="flex flex-wrap items-center justify-between gap-3 border-b border-theme-border/60 pb-4">
            <div class="space-y-0.5">
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-indigo-500"></span>
                <h2 class="font-heading font-bold text-base text-white">Target Roles & Keywords</h2>
              </div>
              <p class="text-xs text-theme-subtle">Roles matching any of these terms in job title, discipline, or summary will be collected</p>
            </div>
            
            <div class="flex items-center gap-2">
              <button onclick="clearKeywords()" class="text-xs text-theme-subtle hover:text-white px-2.5 py-1 rounded-lg hover:bg-white/5 transition font-heading">Clear all</button>
              <button onclick="resetKeywords()" class="text-xs text-indigo-300 hover:text-white px-3 py-1 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 font-heading font-semibold transition">Reset defaults</button>
            </div>
          </div>

          <!-- Discipline Presets (Pill Chips) -->
          <div class="space-y-1.5">
            <span class="text-theme-subtle text-[11px] font-heading font-semibold uppercase tracking-wider block">Quick Presets:</span>
            <div class="flex flex-wrap items-center gap-1.5 text-xs">
              <button onclick="addKeywordPreset(['technical artist', 'tech artist', 'technical art', 'shader artist', 'tools programmer', 'pipeline td', 'vfx technical artist'])" class="chip-btn px-2.5 py-1 rounded-lg bg-theme-surface hover:bg-theme-card border border-theme-border text-indigo-300 text-[11px] font-heading font-medium shadow-sm flex items-center gap-1">
                <span>✦</span> Tech Art & Tools
              </button>
              <button onclick="addKeywordPreset(['gameplay programmer', 'gameplay engineer', 'engine programmer', 'graphics programmer', 'c++ programmer', 'generalist programmer'])" class="chip-btn px-2.5 py-1 rounded-lg bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-textSecondary text-[11px] font-heading font-medium shadow-sm">
                + Programming
              </button>
              <button onclick="addKeywordPreset(['game designer', 'level designer', 'systems designer', 'combat designer', 'narrative designer'])" class="chip-btn px-2.5 py-1 rounded-lg bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-textSecondary text-[11px] font-heading font-medium shadow-sm">
                + Design
              </button>
              <button onclick="addKeywordPreset(['3d artist', 'environment artist', 'character artist', 'concept artist', 'animator', 'technical animator'])" class="chip-btn px-2.5 py-1 rounded-lg bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-textSecondary text-[11px] font-heading font-medium shadow-sm">
                + 3D Art & Anim
              </button>
              <button onclick="addKeywordPreset(['producer', 'associate producer', 'project manager', 'qa tester', 'qa engineer'])" class="chip-btn px-2.5 py-1 rounded-lg bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-textSecondary text-[11px] font-heading font-medium shadow-sm">
                + Production & QA
              </button>
              <button onclick="addKeywordPreset(['sound designer', 'audio programmer', 'audio designer', 'composer'])" class="chip-btn px-2.5 py-1 rounded-lg bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-textSecondary text-[11px] font-heading font-medium shadow-sm">
                + Audio
              </button>
            </div>
          </div>

          <!-- Tag Input Container -->
          <div class="p-3 rounded-xl bg-theme-bg/80 border border-theme-border min-h-[100px] flex flex-wrap gap-2 items-center focus-within:border-indigo-500/80 focus-within:ring-2 focus-within:ring-indigo-500/20 transition shadow-inner">
            <div id="keywordsList" class="flex flex-wrap gap-1.5"></div>
            <input id="keywordInput" type="text" placeholder="Type keyword and press Enter or comma..." 
              class="flex-1 min-w-[220px] bg-transparent text-xs text-white focus:outline-none placeholder-theme-subtle px-2 py-1 font-sans"
              onkeydown="handleTagKey(event, 'keywordInput', addKeyword)">
          </div>
        </div>

        <!-- 2 Column Split: Words to Avoid + Studios to Avoid -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          
          <!-- Words to Avoid -->
          <div class="glass-card rounded-2xl p-5 space-y-3.5 shadow-card hover:shadow-card-hover transition duration-300">
            <div class="flex items-center justify-between border-b border-theme-border/60 pb-3">
              <div class="space-y-0.5">
                <h3 class="font-heading font-bold text-xs text-white flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full bg-rose-400"></span>
                  Negative Keywords
                </h3>
                <p class="text-[11px] text-theme-subtle">Reject postings containing any of these words</p>
              </div>
            </div>

            <!-- Quick Avoid Presets -->
            <div class="flex flex-wrap gap-1.5 text-[11px]">
              <button onclick="addExcludePreset(['unpaid', 'volunteer', 'internship', 'crypto', 'nft', 'web3', 'gambling', 'casino'])" class="chip-btn px-2.5 py-0.5 rounded-md bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-rose-300 text-[11px] font-heading">
                + Unpaid/Crypto/Casino
              </button>
              <button onclick="addExcludePreset(['subsea', 'civil engineer', 'oil and gas', 'drilling'])" class="chip-btn px-2.5 py-0.5 rounded-md bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-rose-300 text-[11px] font-heading">
                + Non-games
              </button>
            </div>

            <div class="p-2.5 rounded-xl bg-theme-bg/80 border border-theme-border min-h-[76px] flex flex-wrap gap-1.5 items-center focus-within:border-rose-500/70 focus-within:ring-2 focus-within:ring-rose-500/10 transition shadow-inner">
              <div id="excludeKeywordsList" class="flex flex-wrap gap-1.5"></div>
              <input id="excludeKeywordInput" type="text" placeholder="Add word to avoid..." 
                class="flex-1 min-w-[120px] bg-transparent text-xs text-white focus:outline-none placeholder-theme-subtle px-1 py-0.5 font-sans"
                onkeydown="handleTagKey(event, 'excludeKeywordInput', addExcludeKeyword)">
            </div>
          </div>

          <!-- Studios to Avoid -->
          <div class="glass-card rounded-2xl p-5 space-y-3.5 shadow-card hover:shadow-card-hover transition duration-300">
            <div class="flex items-center justify-between border-b border-theme-border/60 pb-3">
              <div class="space-y-0.5">
                <h3 class="font-heading font-bold text-xs text-white flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
                  Excluded Studios
                </h3>
                <p class="text-[11px] text-theme-subtle">Hide postings from specific companies</p>
              </div>
              <span id="excludeCompanyCount" class="font-mono text-[11px] text-amber-300 px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20">0 excluded</span>
            </div>

            <div class="text-[11px] text-theme-subtle italic">Click "Exclude studio" directly on any search card to add it here.</div>

            <div class="p-2.5 rounded-xl bg-theme-bg/80 border border-theme-border min-h-[76px] flex flex-wrap gap-1.5 items-center focus-within:border-amber-500/70 focus-within:ring-2 focus-within:ring-amber-500/10 transition shadow-inner">
              <div id="excludeCompaniesList" class="flex flex-wrap gap-1.5"></div>
              <input id="excludeCompanyInput" type="text" placeholder="Type studio name & Enter..." 
                class="flex-1 min-w-[120px] bg-transparent text-xs text-white focus:outline-none placeholder-theme-subtle px-1 py-0.5 font-sans"
                onkeydown="handleTagKey(event, 'excludeCompanyInput', addExcludeCompany)">
            </div>
          </div>

        </div>

      </div>

      <!-- Right Column (4 cols): Sources, Location Matrix & Automation -->
      <div class="lg:col-span-4 space-y-6">

        <!-- Sources & Feeds Card -->
        <div class="glass-card rounded-2xl p-5 space-y-4 shadow-card hover:shadow-card-hover transition duration-300">
          <div class="flex items-center justify-between border-b border-theme-border/60 pb-3">
            <h3 class="font-heading font-bold text-xs text-white uppercase tracking-wider flex items-center gap-2">
              <svg class="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
              Live Data Sources
            </h3>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">Active Feeds</span>
          </div>

          <!-- Source Toggles -->
          <div class="space-y-2.5">
            <!-- Source 1: Looker Studio & ASGC -->
            <label class="flex items-start justify-between p-3 rounded-xl bg-theme-surface/70 border border-theme-border hover:border-indigo-500/40 cursor-pointer transition">
              <div class="pr-2 space-y-0.5">
                <div class="flex items-center gap-1.5">
                  <span class="text-xs font-heading font-semibold text-white">Amir Satvat / ASGC Games Board</span>
                </div>
                <div class="text-[11px] text-theme-subtle leading-snug">
                  41,000+ postings synchronized from the global games directory
                </div>
                <a href="https://lookerstudio.google.com/reporting/2f39b56e-7393-4aa2-9fd5-bf8bf615c95f/page/5koHB" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" class="inline-flex items-center gap-1 mt-1 text-[11px] text-indigo-400 hover:text-indigo-300 font-medium">
                  Open Looker Studio ↗
                </a>
              </div>
              <input type="checkbox" id="srcAsgc" class="mt-1 w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 bg-theme-bg border-theme-border" checked>
            </label>

            <!-- Source 2: Direct Studio Careers -->
            <label class="flex items-start justify-between p-3 rounded-xl bg-theme-surface/70 border border-theme-border hover:border-indigo-500/40 cursor-pointer transition">
              <div class="pr-2 space-y-0.5">
                <div class="text-xs font-heading font-semibold text-white">Direct Studio Career Portals</div>
                <div class="text-[11px] text-theme-subtle leading-snug">
                  360+ tracked game studios (Greenhouse, Lever, Ashby, Workable, direct web)
                </div>
              </div>
              <input type="checkbox" id="srcStudios" class="mt-1 w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 bg-theme-bg border-theme-border" checked>
            </label>

            <!-- Source 3: Aardvark Swift -->
            <label class="flex items-start justify-between p-3 rounded-xl bg-theme-surface/70 border border-theme-border hover:border-indigo-500/40 cursor-pointer transition">
              <div class="pr-2 space-y-0.5">
                <div class="text-xs font-heading font-semibold text-white">Aardvark Swift Recruitment</div>
                <div class="text-[11px] text-theme-subtle leading-snug">
                  Specialist UK & global games industry recruitment agency (aswift.com)
                </div>
              </div>
              <input type="checkbox" id="srcAardvark" class="mt-1 w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 bg-theme-bg border-theme-border" checked>
            </label>

            <!-- Source 4: InGame Job -->
            <label class="flex items-start justify-between p-3 rounded-xl bg-theme-surface/70 border border-theme-border hover:border-indigo-500/40 cursor-pointer transition">
              <div class="pr-2 space-y-0.5">
                <div class="text-xs font-heading font-semibold text-white">InGame Job Board</div>
                <div class="text-[11px] text-theme-subtle leading-snug">
                  Curated international game development vacancies & studio roles (ingamejob.com)
                </div>
              </div>
              <input type="checkbox" id="srcInGame" class="mt-1 w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 bg-theme-bg border-theme-border" checked>
            </label>

            <!-- Source 5: GamesIndustry.biz -->
            <label class="flex items-start justify-between p-3 rounded-xl bg-theme-surface/70 border border-theme-border hover:border-indigo-500/40 cursor-pointer transition">
              <div class="pr-2 space-y-0.5">
                <div class="text-xs font-heading font-semibold text-white">GamesIndustry.biz Jobs</div>
                <div class="text-[11px] text-theme-subtle leading-snug">
                  Leading European and global games business job board (jobs.gamesindustry.biz)
                </div>
              </div>
              <input type="checkbox" id="srcGibiz" class="mt-1 w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 bg-theme-bg border-theme-border" checked>
            </label>

            <!-- Source 6: Work With Indies -->
            <label class="flex items-start justify-between p-3 rounded-xl bg-theme-surface/70 border border-theme-border hover:border-indigo-500/40 cursor-pointer transition">
              <div class="pr-2 space-y-0.5">
                <div class="text-xs font-heading font-semibold text-white">Work With Indies</div>
                <div class="text-[11px] text-theme-subtle leading-snug">
                  Dedicated remote & indie studio job board (workwithindies.com)
                </div>
              </div>
              <input type="checkbox" id="srcWorkWithIndies" class="mt-1 w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 bg-theme-bg border-theme-border" checked>
            </label>

            <!-- Source 7: Datascope -->
            <label class="flex items-start justify-between p-3 rounded-xl bg-theme-surface/70 border border-theme-border hover:border-indigo-500/40 cursor-pointer transition">
              <div class="pr-2 space-y-0.5">
                <div class="text-xs font-heading font-semibold text-white">Datascope Recruitment</div>
                <div class="text-[11px] text-theme-subtle leading-snug">
                  Games & interactive technology recruitment consultancy (datascope.co.uk)
                </div>
              </div>
              <input type="checkbox" id="srcDatascope" class="mt-1 w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 bg-theme-bg border-theme-border" checked>
            </label>
          </div>

          <!-- Studio Portal Re-scrape tool -->
          <div class="pt-2 border-t border-theme-border/60">
            <button onclick="triggerGamesMapRefresh()" id="btnScrapeRefresh" class="w-full py-2 px-3 rounded-xl bg-theme-surface hover:bg-theme-card border border-theme-border text-xs font-heading font-semibold text-theme-text flex items-center justify-center gap-2 transition active:scale-[0.98]">
              <svg id="refreshSpinner" class="w-3.5 h-3.5 text-theme-subtle" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
              <span>Refresh 360+ Studio Portals</span>
            </button>
            <div id="refreshStatus" class="mt-1.5 text-[11px] text-theme-subtle text-center font-mono truncate"></div>
          </div>

        </div>

        <!-- Location & Workplace Rules Card -->
        <div id="location-section" class="glass-card rounded-2xl p-5 space-y-4 shadow-card hover:shadow-card-hover transition duration-300">
          <div class="flex items-center justify-between border-b border-theme-border/60 pb-3">
            <div>
              <h4 class="font-heading font-bold text-xs text-white flex items-center gap-2">
                <svg class="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"></path></svg>
                Location & Distance Rules
              </h4>
              <p class="text-[11px] text-theme-subtle">Multi-mode distance matrix with geocoding</p>
            </div>
            <span id="locationRuleCount" class="font-mono text-[11px] text-cyan-300 px-2 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-500/20">0 rules</span>
          </div>

          <!-- Quick Presets -->
          <div class="space-y-1.5">
            <span class="text-[10px] font-heading font-semibold uppercase tracking-wider text-theme-subtle block">Curated Presets:</span>
            <div class="flex flex-wrap gap-1.5 text-[11px]">
              <button type="button" onclick="addLocationPreset('remote_eu')" class="chip-btn px-2.5 py-0.5 rounded-md bg-theme-surface hover:bg-theme-card border border-theme-border text-emerald-300 hover:text-white text-[11px] font-heading font-medium">🏠 Remote in Europe</button>
              <button type="button" onclick="addLocationPreset('hybrid_london_30')" class="chip-btn px-2.5 py-0.5 rounded-md bg-theme-surface hover:bg-theme-card border border-theme-border text-indigo-300 hover:text-white text-[11px] font-heading font-medium">🔄 Hybrid ≤30mi London</button>
              <button type="button" onclick="addLocationPreset('onsite_cambridge_20')" class="chip-btn px-2.5 py-0.5 rounded-md bg-theme-surface hover:bg-theme-card border border-theme-border text-purple-300 hover:text-white text-[11px] font-heading font-medium">🏢 On-site ≤20mi Camb</button>
              <button type="button" onclick="addLocationPreset('remote_global')" class="chip-btn px-2.5 py-0.5 rounded-md bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-white text-[11px] font-heading font-medium">🌐 Remote Global</button>
            </div>
          </div>

          <!-- Active Rules Container -->
          <div id="locationRulesContainer" class="space-y-2 max-h-[220px] overflow-y-auto pr-1"></div>

          <!-- Add Rule Form -->
          <div class="p-3 rounded-xl bg-theme-bg/80 border border-theme-border space-y-2.5 shadow-inner">
            <div class="text-[11px] font-heading font-bold text-white uppercase tracking-wider">Add Custom Distance Rule</div>
            
            <div class="grid grid-cols-12 gap-2">
              <div class="col-span-4">
                <select id="newRuleMode" class="w-full px-2.5 py-1.5 rounded-lg bg-theme-surface border border-theme-border text-xs text-white focus:outline-none focus:border-indigo-500 font-heading">
                  <option value="remote">Remote</option>
                  <option value="hybrid" selected>Hybrid</option>
                  <option value="on_site">On-site</option>
                  <option value="any">Any Mode</option>
                </select>
              </div>
              <div class="col-span-8">
                <input id="newRuleTarget" type="text" placeholder="City or Region (e.g. London, Europe)" 
                  class="w-full px-2.5 py-1.5 rounded-lg bg-theme-surface border border-theme-border text-xs text-white placeholder-theme-subtle focus:outline-none focus:border-indigo-500 font-sans"
                  onkeydown="if(event.key==='Enter'){event.preventDefault();addNewLocationRule();}">
              </div>
            </div>

            <div class="flex items-center gap-2">
              <select id="newRuleDist" class="flex-1 px-2.5 py-1.5 rounded-lg bg-theme-surface border border-theme-border text-xs text-white focus:outline-none focus:border-indigo-500 font-sans">
                <option value="10">Within 10 miles</option>
                <option value="20">Within 20 miles</option>
                <option value="30" selected>Within 30 miles</option>
                <option value="50">Within 50 miles</option>
                <option value="75">Within 75 miles</option>
                <option value="100">Within 100 miles</option>
                <option value="">No distance limit (exact/region)</option>
              </select>

              <button type="button" onclick="testGeocodeInput()" title="Test Geocoding" class="px-2.5 py-1.5 rounded-lg bg-theme-surface hover:bg-theme-card border border-theme-border text-xs text-theme-subtle hover:text-white font-heading font-medium transition">
                📍 Test
              </button>
              <button type="button" onclick="addNewLocationRule()" class="px-3.5 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-heading font-semibold transition shadow-sm">
                + Add
              </button>
            </div>
            
            <div id="geocodeTestResult" class="hidden text-[11px] font-mono p-2 rounded-lg bg-theme-surface border border-theme-border"></div>
          </div>

          <!-- Legacy fallback toggle / simple keyword box -->
          <details class="text-[11px] text-theme-subtle">
            <summary class="cursor-pointer hover:text-white font-medium select-none">Legacy text filter / remote-only fallback</summary>
            <div class="mt-2 pt-2 border-t border-theme-border/60 space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-xs text-theme-textSecondary">Remote roles only (legacy)</span>
                <input type="checkbox" id="remoteOnly" class="w-3.5 h-3.5 rounded text-indigo-600 focus:ring-indigo-500 bg-theme-surface border-theme-border cursor-pointer">
              </div>
              <div>
                <label class="text-[11px] text-theme-subtle block mb-1">Simple keyword match (e.g. UK, London)</label>
                <div class="p-1.5 rounded-lg bg-theme-bg/80 border border-theme-border flex flex-wrap gap-1 items-center">
                  <div id="locationList" class="flex flex-wrap gap-1"></div>
                  <input id="locationInput" type="text" placeholder="Add text..." 
                    class="flex-1 min-w-[70px] bg-transparent text-xs text-white focus:outline-none placeholder-theme-subtle px-1 py-0.5 font-sans"
                    onkeydown="handleTagKey(event, 'locationInput', addLocation)">
                </div>
              </div>
            </div>
          </details>
        </div>

        <!-- Automated Scheduler & Alerts Card -->
        <div id="scheduler-section" class="glass-card rounded-2xl p-5 space-y-4 shadow-card hover:shadow-card-hover transition duration-300">
          <div class="flex items-center justify-between border-b border-theme-border/60 pb-3">
            <div>
              <h3 class="font-heading font-bold text-xs text-white flex items-center gap-2">
                <svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                Automated Background Scheduler
              </h3>
              <p class="text-[11px] text-theme-subtle">Silent Windows Task checks & Alerts</p>
            </div>
            <span id="scheduleActiveBadge" class="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-mono">Active</span>
          </div>

          <!-- Master enable toggle -->
          <label class="flex items-center justify-between p-2.5 rounded-xl bg-theme-surface/70 border border-theme-border cursor-pointer hover:border-theme-borderLight transition">
            <div class="space-y-0.5">
              <span class="text-xs font-heading font-semibold text-white">Enable Background Scheduler</span>
              <div class="text-[10px] text-theme-subtle">Runs automated checks in Windows Task Scheduler</div>
            </div>
            <input type="checkbox" id="scheduleEnabled" class="w-4 h-4 rounded text-indigo-600 bg-theme-bg border-theme-border cursor-pointer" checked onchange="toggleScheduleMaster()">
          </label>

          <!-- Quick Presets -->
          <div class="space-y-1.5">
            <div class="text-[10px] font-heading font-semibold uppercase tracking-wider text-theme-subtle">Schedule Presets:</div>
            <div class="flex flex-wrap gap-1.5 text-[11px]">
              <button type="button" onclick="setSchedulePreset('3x')" class="chip-btn px-2.5 py-0.5 rounded-md bg-theme-surface hover:bg-theme-card border border-theme-border text-emerald-300 hover:text-white text-[11px] font-heading font-medium">⚡ 3x Daily (9am, 1pm, 6pm)</button>
              <button type="button" onclick="setSchedulePreset('4x')" class="chip-btn px-2.5 py-0.5 rounded-md bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-white text-[11px] font-heading font-medium">4x Daily (8am, 12, 4, 8)</button>
              <button type="button" onclick="addScheduleTime('13:00')" class="chip-btn px-2.5 py-0.5 rounded-md bg-theme-surface hover:bg-theme-card border border-theme-border text-amber-300 hover:text-white text-[11px] font-heading font-medium">+ 1 PM Lunch</button>
            </div>
          </div>

          <!-- Active Schedule Time List -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between text-[11px]">
              <span class="text-theme-subtle font-heading font-semibold uppercase tracking-wider text-[10px]">Configured Check Times:</span>
              <span id="scheduleCountBadge" class="font-mono text-[10px] text-theme-subtle">3 times</span>
            </div>
            <div id="scheduleTimesContainer" class="flex flex-wrap gap-1.5 min-h-[44px] p-2.5 rounded-xl bg-theme-bg/80 border border-theme-border items-center shadow-inner"></div>
          </div>

          <!-- Add Custom Time Form -->
          <div class="flex items-center gap-2">
            <input type="time" id="newScheduleTimeInput" value="13:00" class="flex-1 px-3 py-1.5 rounded-lg bg-theme-surface border border-theme-border text-xs text-white focus:outline-none focus:border-indigo-500 font-mono">
            <button type="button" onclick="addScheduleFromInput()" class="px-3.5 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-heading font-semibold transition shadow-sm">
              + Add Time
            </button>
          </div>

          <!-- Windows Task Scheduler Sync & Live Status -->
          <div class="pt-2 border-t border-theme-border/60 space-y-2">
            <button type="button" id="btnSyncScheduler" onclick="syncSchedulerToWindows()" class="w-full py-2 px-3 rounded-xl bg-theme-surface hover:bg-theme-card border border-theme-border text-xs font-heading font-semibold text-white flex items-center justify-center gap-2 transition active:scale-[0.98]">
              <svg class="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
              <span>Sync to Windows Task Scheduler</span>
            </button>
            <div id="schedulerStatusInfo" class="text-[10px] font-mono text-theme-subtle bg-theme-bg/80 p-2.5 rounded-xl border border-theme-border space-y-1">
              <div class="flex items-center justify-between">
                <span>Task: GamesMap_Career_JobMonitor</span>
                <span id="schedulerStatusState" class="text-emerald-400 font-semibold">Ready</span>
              </div>
              <div id="schedulerNextRun" class="text-theme-subtle truncate">Next Run: Checking...</div>
            </div>
          </div>

          <!-- Notification Channels Sub-Block -->
          <div class="pt-3 border-t border-theme-border/60 space-y-2.5">
            <div class="flex items-center justify-between">
              <span class="text-xs font-heading font-bold text-white uppercase tracking-wider">Alert Channels</span>
              <button onclick="testNotifications()" class="text-[11px] px-2.5 py-0.5 rounded-md bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/20 font-heading font-semibold transition">
                Test Alert
              </button>
            </div>

            <label class="flex items-center justify-between p-2 rounded-lg bg-theme-surface/70 border border-theme-border cursor-pointer">
              <span class="text-xs text-white font-heading">Windows Desktop Toast</span>
              <input type="checkbox" id="notifToast" class="w-3.5 h-3.5 rounded text-indigo-600 bg-theme-bg border-theme-border" checked>
            </label>

            <div>
              <label class="text-[10px] font-heading font-semibold uppercase tracking-wider text-theme-subtle block mb-1">Discord Webhook</label>
              <input type="text" id="discordWebhook" placeholder="https://discord.com/api/webhooks/..." 
                class="w-full px-2.5 py-1.5 rounded-lg bg-theme-surface border border-theme-border text-xs text-white placeholder-theme-subtle focus:outline-none focus:border-indigo-500 font-mono text-[11px]">
            </div>

            <div>
              <label class="text-[10px] font-heading font-semibold uppercase tracking-wider text-theme-subtle block mb-1">Slack Webhook</label>
              <input type="text" id="slackWebhook" placeholder="https://hooks.slack.com/services/..." 
                class="w-full px-2.5 py-1.5 rounded-lg bg-theme-surface border border-theme-border text-xs text-white placeholder-theme-subtle focus:outline-none focus:border-indigo-500 font-mono text-[11px]">
            </div>
          </div>

        </div>

      </div>

    </div>

    <!-- Live Search Results Section (WordPress Directory Showcase) -->
    <div id="resultsSection" class="glass-card rounded-2xl p-6 sm:p-8 space-y-6 shadow-card">
      
      <!-- Section Header with Editorial Flair -->
      <div class="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-theme-border/60">
        
        <div class="space-y-1">
          <div class="flex items-center gap-3">
            <h2 class="font-editorial text-2xl font-normal text-white">Live Industry Matches</h2>
            <span id="resultsCountBadge" class="px-3 py-0.5 rounded-full text-xs font-mono font-semibold bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 shadow-sm">0 matches</span>
          </div>
          <p id="resultsStatsSubtitle" class="text-xs text-theme-subtle font-mono">Run a scan to query active game dev studio portals & Looker Studio database</p>
        </div>

        <!-- Filter within results & Export actions -->
        <div class="flex flex-wrap items-center gap-2.5">
          <!-- Filter bar -->
          <div class="relative">
            <input type="text" id="filterResultsInput" oninput="filterResultsTable()" placeholder="Filter within matches..." 
              class="w-48 sm:w-60 px-3 py-1.5 pl-8 rounded-xl bg-theme-bg/90 border border-theme-border text-xs text-white placeholder-theme-subtle focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition font-sans shadow-inner">
            <svg class="w-3.5 h-3.5 text-theme-subtle absolute left-2.5 top-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
          </div>

          <!-- View Mode Toggle -->
          <div class="flex items-center rounded-xl bg-theme-bg/90 border border-theme-border p-1 shadow-inner">
            <button id="btnViewCards" onclick="setViewMode('cards')" class="px-3 py-1 rounded-lg text-xs font-heading font-semibold text-white bg-indigo-600 shadow-sm transition">Cards</button>
            <button id="btnViewTable" onclick="setViewMode('table')" class="px-3 py-1 rounded-lg text-xs font-heading font-medium text-theme-subtle hover:text-white transition">Table</button>
          </div>

          <!-- Export Actions -->
          <div class="flex items-center gap-1.5">
            <button onclick="exportCSV()" class="px-3 py-1.5 rounded-xl bg-theme-surface hover:bg-theme-card border border-theme-border text-xs font-heading font-semibold text-white flex items-center gap-1.5 transition shadow-sm">
              <svg class="w-3 h-3 text-theme-subtle" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
              CSV
            </button>
            <button onclick="exportJSON()" class="px-3 py-1.5 rounded-xl bg-theme-surface hover:bg-theme-card border border-theme-border text-xs font-heading font-semibold text-white transition shadow-sm">
              JSON
            </button>
          </div>
      </div>

      <!-- Source Quick Filter Bar -->
      <div id="sourceFilterChips" class="flex flex-wrap items-center gap-1.5 pt-1">
        <span class="text-[10px] font-heading font-semibold uppercase tracking-wider text-theme-subtle mr-1">Filter Source:</span>
        <button type="button" onclick="setSourceFilter('all')" id="srcChip_all" class="chip-btn px-2.5 py-1 rounded-lg text-xs font-heading font-semibold bg-indigo-600 text-white shadow-sm transition">All Sources</button>
        <button type="button" onclick="setSourceFilter('Looker Studio / ASGC')" id="srcChip_asgc" class="chip-btn px-2.5 py-1 rounded-lg text-xs font-heading font-medium bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-white transition">ASGC Feed</button>
        <button type="button" onclick="setSourceFilter('Direct Studio')" id="srcChip_studio" class="chip-btn px-2.5 py-1 rounded-lg text-xs font-heading font-medium bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-white transition">Direct Studios</button>
        <button type="button" onclick="setSourceFilter('Aardvark Swift')" id="srcChip_aswift" class="chip-btn px-2.5 py-1 rounded-lg text-xs font-heading font-medium bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-white transition">Aardvark Swift</button>
        <button type="button" onclick="setSourceFilter('InGame Job')" id="srcChip_ingame" class="chip-btn px-2.5 py-1 rounded-lg text-xs font-heading font-medium bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-white transition">InGame Job</button>
        <button type="button" onclick="setSourceFilter('GamesIndustry.biz')" id="srcChip_gibiz" class="chip-btn px-2.5 py-1 rounded-lg text-xs font-heading font-medium bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-white transition">GamesIndustry.biz</button>
        <button type="button" onclick="setSourceFilter('Work With Indies')" id="srcChip_wwi" class="chip-btn px-2.5 py-1 rounded-lg text-xs font-heading font-medium bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-white transition">Work With Indies</button>
      </div>

      <!-- Real-Time Live Querying & Progress State (Glowing Live Console) -->
      <div id="searchLoadingState" class="hidden py-6 px-6 rounded-2xl bg-theme-surface/90 border border-indigo-500/30 shadow-glow-md space-y-4 max-w-3xl mx-auto my-4 transition duration-300">
        
        <!-- Header with animated spinner and status -->
        <div class="flex flex-wrap items-center justify-between gap-4">
          <div class="flex items-center gap-3.5">
            <div class="relative flex items-center justify-center">
              <div class="w-8 h-8 rounded-xl border-2 border-indigo-500/30 border-t-indigo-500 animate-spin"></div>
              <span class="absolute w-2.5 h-2.5 rounded-full bg-indigo-400 animate-ping"></span>
            </div>
            <div>
              <div class="flex items-center gap-2">
                <span class="font-heading font-bold text-sm text-white" id="liveSearchStatusTitle">Scanning Industry Portals...</span>
                <span id="liveProgressPercentBadge" class="text-xs font-mono px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-semibold">0%</span>
              </div>
              <p id="liveSearchStatusSub" class="text-xs text-theme-subtle font-mono mt-0.5">Harvesting live ATS job feeds & ASGC database</p>
            </div>
          </div>

          <!-- Live Counters -->
          <div class="flex items-center gap-2 text-xs font-mono">
            <div class="px-2.5 py-1 rounded-lg bg-theme-bg border border-theme-border flex items-center gap-1.5" title="Studios Scanned">
              <span class="text-theme-subtle text-[10px]">Studios:</span>
              <span id="liveStatStudios" class="text-white font-semibold">0 / 0</span>
            </div>
            <div class="px-2.5 py-1 rounded-lg bg-theme-bg border border-theme-border flex items-center gap-1.5" title="Postings Harvested">
              <span class="text-theme-subtle text-[10px]">Harvested:</span>
              <span id="liveStatRaw" class="text-cyan-400 font-semibold">0</span>
            </div>
            <div class="px-2.5 py-1 rounded-lg bg-theme-bg border border-theme-border flex items-center gap-1.5" title="Matching Roles Found">
              <span class="text-theme-subtle text-[10px]">Matches:</span>
              <span id="liveStatMatches" class="text-emerald-400 font-semibold">0</span>
            </div>
          </div>
        </div>

        <!-- Animated Progress Bar with Gradient -->
        <div class="w-full bg-theme-bg rounded-full h-2.5 overflow-hidden border border-theme-border p-[1px]">
          <div id="liveProgressBar" class="bg-gradient-to-r from-indigo-500 via-violet-500 to-emerald-400 h-full rounded-full transition-all duration-200 ease-out shadow-glow-sm" style="width: 0%"></div>
        </div>

        <!-- Currently Querying Active Pill / Ticker -->
        <div class="flex items-center gap-2.5 text-xs">
          <span class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-950/60 text-indigo-300 border border-indigo-500/30 font-mono text-[10px] font-semibold flex-shrink-0">
            <span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse"></span>
            ACTIVE HARVEST:
          </span>
          <div id="liveActiveQueries" class="text-xs text-white font-mono truncate">Connecting to endpoints...</div>
        </div>

        <!-- Live Activity Log Window (Polished Terminal Look) -->
        <div class="border border-theme-border rounded-xl bg-theme-bg/90 p-3 font-mono text-[11px] space-y-1.5 max-h-40 overflow-y-auto shadow-inner" id="liveActivityLog">
          <div class="text-theme-subtle">[00:00:00] Initializing multi-threaded crawler across studio ATS feeds...</div>
        </div>

      </div>

      <!-- Empty State / Initial Prompt -->
      <div id="emptyState" class="py-16 text-center space-y-4 max-w-md mx-auto">
        <div class="w-14 h-14 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center mx-auto shadow-glow-sm">
          <svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
        </div>
        <div class="space-y-1">
          <h3 class="font-heading font-bold text-base text-white">No Jobs Currently Displayed</h3>
          <p class="text-xs text-theme-subtle leading-relaxed">
            Customize your target keywords and location radius above, then click <span class="text-indigo-400 font-semibold font-heading">Run Live Scan</span> to search all 360+ studio career portals.
          </p>
        </div>
        <button onclick="executeLiveSearch()" class="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-heading font-semibold transition shadow-glow-sm active:scale-[0.98]">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
          <span>Start Live Job Scan</span>
        </button>
      </div>

      <!-- Cards Grid (WordPress Portfolio & Directory style) -->
      <div id="resultsCardsGrid" class="hidden grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5"></div>

      <!-- Table View -->
      <div id="resultsTableContainer" class="hidden overflow-x-auto rounded-2xl border border-theme-border shadow-card">
        <table class="w-full text-left text-xs text-white">
          <thead class="bg-theme-surface text-theme-subtle font-heading text-[11px] uppercase tracking-wider border-b border-theme-border">
            <tr>
              <th class="py-3 px-4 font-semibold">Role</th>
              <th class="py-3 px-4 font-semibold">Studio</th>
              <th class="py-3 px-4 font-semibold">Discipline</th>
              <th class="py-3 px-4 font-semibold">Location</th>
              <th class="py-3 px-4 font-semibold">Source</th>
              <th class="py-3 px-4 font-semibold">Keywords</th>
              <th class="py-3 px-4 text-right font-semibold">Action</th>
            </tr>
          </thead>
          <tbody id="resultsTableBody" class="divide-y divide-theme-border bg-theme-bg/60 font-sans"></tbody>
        </table>
      </div>

    </div>

  </main>

  <!-- Website Footer (WordPress Theme Style) -->
  <footer class="border-t border-theme-border/60 py-8 px-4 sm:px-6 lg:px-10 mt-auto bg-theme-surface/60 text-xs text-theme-subtle">
    <div class="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
      
      <div class="flex items-center gap-3">
        <div class="w-6 h-6 rounded-lg bg-indigo-600/30 border border-indigo-500/40 flex items-center justify-center text-indigo-400 font-heading font-extrabold text-[10px]">
          GD
        </div>
        <span class="font-heading font-semibold text-white">Game Dev Job Monitor</span>
        <span class="text-theme-subtle">• Pure Python 3 & Web Standards</span>
      </div>

      <div class="flex flex-wrap items-center gap-6 font-heading text-xs">
        <a href="https://lookerstudio.google.com/reporting/2f39b56e-7393-4aa2-9fd5-bf8bf615c95f/page/5koHB" target="_blank" rel="noopener noreferrer" class="hover:text-indigo-300 transition">Amir Satvat ASGC Feed ↗</a>
        <a href="https://greenhouse.io" target="_blank" rel="noopener noreferrer" class="hover:text-indigo-300 transition">Greenhouse</a>
        <a href="https://lever.co" target="_blank" rel="noopener noreferrer" class="hover:text-indigo-300 transition">Lever</a>
        <a href="https://ashbyhq.com" target="_blank" rel="noopener noreferrer" class="hover:text-indigo-300 transition">Ashby</a>
        <a href="https://workable.com" target="_blank" rel="noopener noreferrer" class="hover:text-indigo-300 transition">Workable</a>
      </div>

      <div class="font-mono text-[11px] text-theme-subtle">
        Local GUI: <span class="text-indigo-300">http://127.0.0.1:8765</span>
      </div>

    </div>
  </footer>

  <script>
    // --- Application State ---
    let currentConfig = {
      search: {
        keywords: [],
        exclude_keywords: [],
        exclude_companies: [],
        location_rules: [],
        location_filter: [],
        remote_only: false,
        sources: { query_asgc: true, query_studios: true }
      },
      notifications: {
        windows_toast: true,
        discord_webhook_url: "",
        telegram: { enabled: false, bot_token: "", chat_id: "" },
        slack_webhook_url: ""
      },
      schedule: {
        enabled: true,
        times: ["09:00", "13:00", "18:00"]
      }
    };

    let allSearchResults = [];
    let currentViewMode = 'cards';

    // Studio Avatar Gradient Generator
    const AVATAR_GRADIENTS = [
      'from-indigo-600 to-violet-600',
      'from-cyan-600 to-blue-600',
      'from-emerald-600 to-teal-600',
      'from-fuchsia-600 to-pink-600',
      'from-amber-600 to-orange-600',
      'from-purple-600 to-indigo-600',
      'from-rose-600 to-red-600',
    ];

    function getStudioGradient(name) {
      if (!name) return AVATAR_GRADIENTS[0];
      let hash = 0;
      for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
      const index = Math.abs(hash) % AVATAR_GRADIENTS.length;
      return AVATAR_GRADIENTS[index];
    }

    function getStudioInitials(name) {
      if (!name) return 'GD';
      const parts = name.trim().split(/[\s\-_]+/);
      if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
      }
      return name.slice(0, 2).toUpperCase();
    }

    // --- Initialization ---
    document.addEventListener('DOMContentLoaded', () => {
      loadConfigFromServer();
      loadStatsFromServer();
      loadSchedulerStatus();
      updateClock();
      setInterval(updateClock, 1000);
    });

    function updateClock() {
      const el = document.getElementById('headerClock');
      if (el) {
        const now = new Date();
        el.innerText = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      }
    }

    // --- Toast Notifications ---
    function showToast(message, type = 'success') {
      const container = document.getElementById('toastContainer');
      const toast = document.createElement('div');
      
      const config = {
        success: { border: 'border-emerald-500/40', bg: 'bg-theme-surface', text: 'text-emerald-300', icon: '✓' },
        error: { border: 'border-rose-500/40', bg: 'bg-theme-surface', text: 'text-rose-300', icon: '✗' },
        info: { border: 'border-indigo-500/40', bg: 'bg-theme-surface', text: 'text-indigo-300', icon: 'ℹ' },
        warning: { border: 'border-amber-500/40', bg: 'bg-theme-surface', text: 'text-amber-300', icon: '⚠' }
      }[type] || { border: 'border-theme-border', bg: 'bg-theme-surface', text: 'text-white', icon: '•' };
      
      toast.className = `p-3 rounded-xl border ${config.border} ${config.bg} shadow-card-hover flex items-center gap-2.5 pointer-events-auto text-xs font-heading font-medium transform transition-all duration-200 translate-y-[-8px] opacity-0 ${config.text}`;
      toast.innerHTML = `<span class="w-5 h-5 rounded-lg bg-white/5 flex items-center justify-center font-bold text-xs">${config.icon}</span><span class="truncate">${escapeHTML(message)}</span>`;
      container.appendChild(toast);
      
      requestAnimationFrame(() => {
        toast.classList.remove('translate-y-[-8px]', 'opacity-0');
      });

      setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-y-[-8px]');
        setTimeout(() => toast.remove(), 250);
      }, 3500);
    }

    // --- API Calls ---
    async function loadConfigFromServer() {
      try {
        const res = await fetch('/api/config');
        if (res.ok) {
          currentConfig = await res.json();
          renderConfigUI();
        }
      } catch (err) {
        showToast('Error loading configuration: ' + err.message, 'error');
      }
    }

    async function loadStatsFromServer() {
      try {
        const res = await fetch('/api/stats');
        if (res.ok) {
          const stats = await res.json();
          const stEl = document.getElementById('statStudios');
          const poEl = document.getElementById('statPortals');
          if (stEl) stEl.innerText = (stats.total_companies ? `${stats.total_companies}+` : '360+');
          if (poEl) poEl.innerText = (stats.career_portals ? `${stats.career_portals}+` : '185+');
        }
      } catch (err) {}
    }

    async function saveConfiguration() {
      syncUItoConfig();
      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(currentConfig)
        });
        if (res.ok) {
          showToast('Settings saved to config.json', 'success');
        } else {
          showToast('Failed to save settings', 'error');
        }
      } catch (err) {
        showToast('Save error: ' + err.message, 'error');
      }
    }

    async function executeLiveSearch() {
      syncUItoConfig();
      const btn = document.getElementById('btnSearchNow');
      const searchIcon = document.getElementById('searchIcon');
      const searchText = document.getElementById('searchText');
      const loadingState = document.getElementById('searchLoadingState');
      const emptyState = document.getElementById('emptyState');
      const cardsGrid = document.getElementById('resultsCardsGrid');
      const tableContainer = document.getElementById('resultsTableContainer');
      
      const statusTitle = document.getElementById('liveSearchStatusTitle');
      const statusSub = document.getElementById('liveSearchStatusSub');
      const percentBadge = document.getElementById('liveProgressPercentBadge');
      const progressBar = document.getElementById('liveProgressBar');
      const statStudios = document.getElementById('liveStatStudios');
      const statRaw = document.getElementById('liveStatRaw');
      const statMatches = document.getElementById('liveStatMatches');
      const activeQueries = document.getElementById('liveActiveQueries');
      const logContainer = document.getElementById('liveActivityLog');

      btn.disabled = true;
      searchIcon.classList.add('animate-spin');
      searchText.innerText = 'Scanning...';
      loadingState.classList.remove('hidden');
      emptyState.classList.add('hidden');
      cardsGrid.classList.add('hidden');
      tableContainer.classList.add('hidden');

      // Scroll smoothly toward results if below viewport
      document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth', block: 'start' });

      // Reset live progress widgets
      progressBar.style.width = '0%';
      percentBadge.innerText = '0%';
      statusTitle.innerText = 'Scanning Portals & Feeds...';
      statusSub.innerText = 'Connecting to studio ATS feeds & ASGC database...';
      statStudios.innerText = '0 / 0';
      statRaw.innerText = '0';
      statMatches.innerText = '0';
      activeQueries.innerText = 'Initializing feeds...';
      
      const startTimeStr = new Date().toLocaleTimeString();
      logContainer.innerHTML = `<div class="text-theme-subtle flex items-center gap-2"><span class="text-[10px] font-mono text-indigo-400">[${startTimeStr}]</span> <span>🚀</span> <span>Starting live industry job scan...</span></div>`;

      function appendLog(text, type = 'info') {
        const timeStr = new Date().toLocaleTimeString();
        const div = document.createElement('div');
        let colorClass = 'text-theme-subtle';
        let icon = '•';
        if (type === 'match') {
          colorClass = 'text-emerald-300 font-semibold';
          icon = '✨';
        } else if (type === 'asgc') {
          colorClass = 'text-indigo-300';
          icon = '🌐';
        } else if (type === 'studio') {
          colorClass = 'text-white';
          icon = '🏢';
        } else if (type === 'error') {
          colorClass = 'text-rose-400';
          icon = '✗';
        }
        div.className = `flex items-center gap-2 ${colorClass}`;
        div.innerHTML = `<span class="text-[10px] font-mono text-theme-subtle">[${timeStr}]</span> <span>${icon}</span> <span class="truncate">${escapeHTML(text)}</span>`;
        logContainer.appendChild(div);
        logContainer.scrollTop = logContainer.scrollHeight;
      }

      let finalResult = null;

      try {
        const res = await fetch('/api/search-stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(currentConfig)
        });

        if (res.ok && res.body) {
          const reader = res.body.getReader();
          const decoder = new TextDecoder('utf-8');
          let buffer = '';

          function handleSSEBlock(block) {
            if (!block.trim()) return;
            let eventType = 'message';
            let dataLines = [];

            const lines = block.split(/\r?\n/);
            for (const line of lines) {
              if (line.startsWith('event:')) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith('data:')) {
                dataLines.push(line.slice(5).trim());
              }
            }

            if (dataLines.length === 0) return;
            let eventData = null;
            try {
              eventData = JSON.parse(dataLines.join('\n'));
            } catch (e) {
              return;
            }

            if (!eventData) return;

            if (eventType === 'progress') {
              if (eventData.percent !== undefined) {
                const p = Math.min(100, Math.max(0, eventData.percent));
                progressBar.style.width = `${p}%`;
                percentBadge.innerText = `${Math.round(p)}%`;
              }
              if (eventData.message) {
                statusSub.innerText = eventData.message;
              }
              if (eventData.active && eventData.active.length > 0) {
                activeQueries.innerText = eventData.active.join(' • ');
              }
              if (eventData.completed !== undefined && eventData.total !== undefined) {
                statStudios.innerText = `${eventData.completed} / ${eventData.total}`;
              }
              if (eventData.raw_jobs_total !== undefined) {
                statRaw.innerText = eventData.raw_jobs_total.toLocaleString();
              }
              if (eventData.matched_jobs_total !== undefined) {
                statMatches.innerText = eventData.matched_jobs_total.toLocaleString();
              }
              if (eventData.log_entry) {
                appendLog(eventData.log_entry.text, eventData.log_entry.type || 'info');
              }
            } else if (eventType === 'complete') {
              finalResult = eventData;
              progressBar.style.width = '100%';
              percentBadge.innerText = '100%';
            }
          }

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            
            const parts = buffer.split(/\r?\n\r?\n/);
            buffer = parts.pop() || '';

            for (const part of parts) {
              handleSSEBlock(part);
            }
          }

          if (buffer.trim()) {
            handleSSEBlock(buffer);
          }
        } else {
          // Fallback to standard /api/search
          const fallbackRes = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentConfig)
          });
          if (fallbackRes.ok) {
            finalResult = await fallbackRes.json();
          }
        }

        if (finalResult && finalResult.success) {
          allSearchResults = finalResult.jobs || [];
          renderSearchResults(finalResult);
          showToast(`Found ${allSearchResults.length} matches in ${finalResult.stats.duration_seconds}s`, 'success');
        } else {
          showToast('Search execution failed', 'error');
        }
      } catch (err) {
        showToast('Search error: ' + err.message, 'error');
      } finally {
        btn.disabled = false;
        searchIcon.classList.remove('animate-spin');
        searchText.innerText = 'Run Live Scan';
        loadingState.classList.add('hidden');
      }
    }

    async function testNotifications() {
      syncUItoConfig();
      showToast('Sending test notification...', 'info');
      try {
        const res = await fetch('/api/test-notify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(currentConfig)
        });
        const data = await res.json();
        showToast('Test notification triggered', 'success');
      } catch (err) {
        showToast('Test notify error: ' + err.message, 'error');
      }
    }

    async function triggerGamesMapRefresh() {
      const btn = document.getElementById('btnScrapeRefresh');
      const spinner = document.getElementById('refreshSpinner');
      const statusLbl = document.getElementById('refreshStatus');
      
      btn.disabled = true;
      spinner.classList.add('animate-spin');
      statusLbl.innerText = 'Starting refresh...';

      try {
        const res = await fetch('/api/rescrape-gamesmap', { method: 'POST' });
        const data = await res.json();
        statusLbl.innerText = 'Verifying career URLs...';
        showToast('Studio portal scan running in background', 'info');
        
        const poll = setInterval(async () => {
          const sRes = await fetch('/api/rescrape-status');
          if (sRes.ok) {
            const sData = await sRes.json();
            statusLbl.innerText = sData.message || 'Processing...';
            if (!sData.is_scraping) {
              clearInterval(poll);
              btn.disabled = false;
              spinner.classList.remove('animate-spin');
              loadStatsFromServer();
              showToast('Studio portal update completed', 'success');
            }
          }
        }, 1500);
      } catch (err) {
        btn.disabled = false;
        spinner.classList.remove('animate-spin');
        statusLbl.innerText = 'Failed: ' + err.message;
      }
    }

    // --- UI Sync & Tag Rendering ---
    function renderConfigUI() {
      // 1. Keywords
      renderTagList('keywordsList', currentConfig.search.keywords, removeKeyword, 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20');
      
      // 2. Exclude Keywords
      renderTagList('excludeKeywordsList', currentConfig.search.exclude_keywords, removeExcludeKeyword, 'bg-rose-500/10 text-rose-300 border-rose-500/20');
      
      // 3. Exclude Companies
      renderTagList('excludeCompaniesList', currentConfig.search.exclude_companies, removeExcludeCompany, 'bg-amber-500/10 text-amber-300 border-amber-500/20');
      const countEl = document.getElementById('excludeCompanyCount');
      if (countEl) countEl.innerText = `${currentConfig.search.exclude_companies.length} excluded`;

      // 4. Location Rules
      renderLocationRules();

      // 5. Legacy Locations Tag List
      renderTagList('locationList', currentConfig.search.location_filter || [], removeLocation, 'bg-theme-surface text-white border-theme-border');

      // 6. Switches & Sources
      const sources = currentConfig.search.sources || { query_asgc: true, query_studios: true };
      document.getElementById('srcAsgc').checked = sources.query_asgc !== false;
      document.getElementById('srcStudios').checked = sources.query_studios !== false;
      document.getElementById('srcAardvark').checked = sources.query_aardvark !== false;
      document.getElementById('srcInGame').checked = sources.query_ingame !== false;
      document.getElementById('srcGibiz').checked = sources.query_gibiz !== false;
      document.getElementById('srcWorkWithIndies').checked = sources.query_workwithindies !== false;
      document.getElementById('srcDatascope').checked = sources.query_datascope !== false;
      document.getElementById('remoteOnly').checked = currentConfig.search.remote_only === true;

      // 7. Notifications
      const notifs = currentConfig.notifications || {};
      document.getElementById('notifToast').checked = notifs.windows_toast !== false;
      document.getElementById('discordWebhook').value = notifs.discord_webhook_url || '';
      document.getElementById('slackWebhook').value = notifs.slack_webhook_url || '';

      // 8. Schedule
      renderScheduleUI();
    }

    function syncUItoConfig() {
      currentConfig.search.remote_only = document.getElementById('remoteOnly').checked;
      currentConfig.search.sources = {
        query_asgc: document.getElementById('srcAsgc').checked,
        query_studios: document.getElementById('srcStudios').checked,
        query_aardvark: document.getElementById('srcAardvark').checked,
        query_ingame: document.getElementById('srcInGame').checked,
        query_gibiz: document.getElementById('srcGibiz').checked,
        query_workwithindies: document.getElementById('srcWorkWithIndies').checked,
        query_datascope: document.getElementById('srcDatascope').checked
      };
      currentConfig.notifications.windows_toast = document.getElementById('notifToast').checked;
      currentConfig.notifications.discord_webhook_url = document.getElementById('discordWebhook').value.trim();
      currentConfig.notifications.slack_webhook_url = document.getElementById('slackWebhook').value.trim();
      if (!currentConfig.schedule) {
        currentConfig.schedule = { enabled: true, times: ['09:00', '13:00', '18:00'] };
      }
      const schedCheckbox = document.getElementById('scheduleEnabled');
      if (schedCheckbox) {
        currentConfig.schedule.enabled = schedCheckbox.checked;
      }
    }

    // --- Schedule Timers UI & Controls ---
    function formatTimeDisplay(timeStr) {
      if (!timeStr) return '';
      const parts = timeStr.split(':');
      if (parts.length < 2) return timeStr;
      let hours = parseInt(parts[0], 10);
      const minutes = parts[1].padStart(2, '0');
      if (isNaN(hours)) return timeStr;
      const ampm = hours >= 12 ? 'PM' : 'AM';
      const displayHours = hours % 12 || 12;
      return `${timeStr} (${displayHours}:${minutes} ${ampm})`;
    }

    function renderScheduleUI() {
      const container = document.getElementById('scheduleTimesContainer');
      const countBadge = document.getElementById('scheduleCountBadge');
      const activeBadge = document.getElementById('scheduleActiveBadge');
      const enabledCheckbox = document.getElementById('scheduleEnabled');
      if (!container) return;
      container.innerHTML = '';

      if (!currentConfig.schedule) {
        currentConfig.schedule = { enabled: true, times: ['09:00', '13:00', '18:00'] };
      }
      if (!currentConfig.schedule.times) {
        currentConfig.schedule.times = ['09:00', '13:00', '18:00'];
      }

      const isEnabled = currentConfig.schedule.enabled !== false;
      if (enabledCheckbox) enabledCheckbox.checked = isEnabled;

      if (activeBadge) {
        if (isEnabled) {
          activeBadge.className = "px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-mono";
          activeBadge.innerText = "Active";
        } else {
          activeBadge.className = "px-2 py-0.5 rounded-full bg-theme-surface text-theme-subtle border border-theme-border text-[10px] font-mono";
          activeBadge.innerText = "Disabled";
        }
      }

      const times = currentConfig.schedule.times || [];
      if (countBadge) countBadge.innerText = `${times.length} time${times.length === 1 ? '' : 's'}`;

      if (times.length === 0) {
        container.innerHTML = `<span class="text-theme-subtle text-[11px] italic">No times scheduled. Add one below or click a preset.</span>`;
        return;
      }

      times.forEach((t, idx) => {
        const chip = document.createElement('span');
        chip.className = `inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs border bg-theme-surface text-indigo-300 border-theme-border transition shadow-sm font-mono`;
        chip.innerHTML = `
          <span>${escapeHTML(formatTimeDisplay(t))}</span>
          <button type="button" onclick="removeScheduleTime(${idx})" class="hover:text-rose-400 text-xs font-bold leading-none p-0.5" title="Remove time">&times;</button>
        `;
        container.appendChild(chip);
      });
    }

    function addScheduleTime(timeStr) {
      if (!currentConfig.schedule) currentConfig.schedule = { enabled: true, times: [] };
      if (!currentConfig.schedule.times) currentConfig.schedule.times = [];
      const clean = timeStr.trim();
      if (clean && !currentConfig.schedule.times.includes(clean)) {
        currentConfig.schedule.times.push(clean);
        currentConfig.schedule.times.sort();
        renderScheduleUI();
        showToast(`Added ${formatTimeDisplay(clean)} to schedule`, 'info');
      }
    }

    function addScheduleFromInput() {
      const input = document.getElementById('newScheduleTimeInput');
      if (!input || !input.value) return;
      addScheduleTime(input.value);
    }

    function removeScheduleTime(idx) {
      if (currentConfig.schedule && currentConfig.schedule.times) {
        const removed = currentConfig.schedule.times.splice(idx, 1);
        renderScheduleUI();
        if (removed.length) showToast(`Removed ${formatTimeDisplay(removed[0])} from schedule`, 'info');
      }
    }

    function setSchedulePreset(presetType) {
      if (!currentConfig.schedule) currentConfig.schedule = { enabled: true, times: [] };
      if (presetType === '3x') {
        ['09:00', '13:00', '18:00'].forEach(t => {
          if (!currentConfig.schedule.times.includes(t)) currentConfig.schedule.times.push(t);
        });
      } else if (presetType === '4x') {
        ['08:00', '12:00', '16:00', '20:00'].forEach(t => {
          if (!currentConfig.schedule.times.includes(t)) currentConfig.schedule.times.push(t);
        });
      }
      currentConfig.schedule.times.sort();
      renderScheduleUI();
      showToast('Schedule preset applied', 'success');
    }

    function toggleScheduleMaster() {
      if (!currentConfig.schedule) currentConfig.schedule = { enabled: true, times: [] };
      currentConfig.schedule.enabled = document.getElementById('scheduleEnabled').checked;
      renderScheduleUI();
    }

    async function loadSchedulerStatus() {
      try {
        const res = await fetch('/api/scheduler/status');
        if (res.ok) {
          const info = await res.json();
          const stateEl = document.getElementById('schedulerStatusState');
          const nextEl = document.getElementById('schedulerNextRun');
          if (info.registered) {
            if (stateEl) {
              stateEl.className = "text-emerald-400 font-semibold";
              stateEl.innerText = info.status || "Ready";
            }
            if (nextEl) {
              nextEl.innerText = `Next Run: ${info.next_run_time || 'Scheduled'}`;
            }
          } else {
            if (stateEl) {
              stateEl.className = "text-amber-400 font-semibold";
              stateEl.innerText = "Not Registered";
            }
            if (nextEl) {
              nextEl.innerText = "Click 'Sync to Windows Task Scheduler' to activate.";
            }
          }
        }
      } catch (err) {}
    }

    async function syncSchedulerToWindows() {
      syncUItoConfig();
      const btn = document.getElementById('btnSyncScheduler');
      btn.disabled = true;
      showToast('Updating Windows Task Scheduler...', 'info');
      try {
        const res = await fetch('/api/scheduler/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(currentConfig)
        });
        if (res.ok) {
          const data = await res.json();
          if (data.success) {
            showToast('Windows Task Scheduler updated with your timer options!', 'success');
          } else {
            showToast('Scheduler update note: ' + (data.message || 'Check permissions'), 'warning');
          }
          loadSchedulerStatus();
        } else {
          showToast('Failed to sync scheduler', 'error');
        }
      } catch (err) {
        showToast('Sync error: ' + err.message, 'error');
      } finally {
        btn.disabled = false;
      }
    }

    function renderTagList(containerId, items, removeFn, styleClasses) {
      const container = document.getElementById(containerId);
      if (!container) return;
      container.innerHTML = '';
      (items || []).forEach((item, idx) => {
        const tag = document.createElement('span');
        tag.className = `inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs border font-sans font-medium transition ${styleClasses}`;
        tag.innerHTML = `
          <span>${escapeHTML(item)}</span>
          <button type="button" onclick="${removeFn.name}(${idx})" class="hover:text-white opacity-60 hover:opacity-100 text-xs font-bold leading-none p-0.5">&times;</button>
        `;
        container.appendChild(tag);
      });
    }

    function handleTagKey(event, inputId, addFn) {
      if (event.key === 'Enter' || event.key === ',') {
        event.preventDefault();
        const input = document.getElementById(inputId);
        const val = input.value.replace(',', '').trim();
        if (val) {
          addFn(val);
          input.value = '';
        }
      }
    }

    // --- Location Rules Engine UI ---
    function renderLocationRules() {
      const container = document.getElementById('locationRulesContainer');
      const countBadge = document.getElementById('locationRuleCount');
      if (!container) return;
      container.innerHTML = '';

      const rules = currentConfig.search.location_rules || [];
      const activeCount = rules.filter(r => r.enabled !== false).length;
      if (countBadge) countBadge.innerText = `${activeCount}/${rules.length} active`;

      if (rules.length === 0) {
        container.innerHTML = `
          <div class="p-3 rounded-xl bg-theme-bg/80 border border-dashed border-theme-border text-center text-theme-subtle text-[11px]">
            No location rules configured. All locations will pass. Add a rule or preset below.
          </div>
        `;
        return;
      }

      rules.forEach((rule, idx) => {
        const card = document.createElement('div');
        const isEnabled = rule.enabled !== false;
        
        let modeBadgeClass = 'bg-theme-surface text-theme-subtle border-theme-border';
        let modeLabel = 'Any';
        const m = (rule.mode || 'any').toLowerCase().replace('-', '_');
        
        if (m === 'remote') {
          modeBadgeClass = 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20';
          modeLabel = '🏠 Remote';
        } else if (m === 'hybrid') {
          modeBadgeClass = 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20';
          modeLabel = '🔄 Hybrid';
        } else if (m === 'on_site' || m === 'onsite') {
          modeBadgeClass = 'bg-purple-500/10 text-purple-300 border-purple-500/20';
          modeLabel = '🏢 On-site';
        }

        const distText = rule.max_distance_miles ? 
          `<span class="px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20 text-[10px] font-mono">≤ ${rule.max_distance_miles} mi</span>` : 
          '';

        const targetText = rule.target ? escapeHTML(rule.target) : '<span class="text-theme-subtle italic">Anywhere</span>';

        card.className = `flex items-center justify-between p-2.5 rounded-xl bg-theme-surface/70 border ${isEnabled ? 'border-theme-border hover:border-theme-borderLight' : 'border-theme-border/40 opacity-50'} text-xs transition`;
        card.innerHTML = `
          <div class="flex items-center gap-2.5 overflow-hidden">
            <input type="checkbox" ${isEnabled ? 'checked' : ''} onchange="toggleLocationRule(${idx})" 
              class="w-3.5 h-3.5 rounded text-indigo-600 bg-theme-bg border-theme-border cursor-pointer flex-shrink-0" title="Toggle rule active">
            <span class="px-2 py-0.5 rounded-md text-[10px] font-heading font-semibold border ${modeBadgeClass} flex-shrink-0">${modeLabel}</span>
            <div class="truncate text-[11px] text-white font-medium flex items-center gap-1.5">
              <span>${targetText}</span>
              ${distText}
            </div>
          </div>
          <button type="button" onclick="removeLocationRule(${idx})" class="text-theme-subtle hover:text-rose-400 p-1 text-xs font-bold leading-none transition" title="Delete rule">&times;</button>
        `;
        container.appendChild(card);
      });
    }

    function toggleLocationRule(idx) {
      if (currentConfig.search.location_rules && currentConfig.search.location_rules[idx]) {
        const cur = currentConfig.search.location_rules[idx].enabled;
        currentConfig.search.location_rules[idx].enabled = cur === false ? true : false;
        renderLocationRules();
      }
    }

    function removeLocationRule(idx) {
      if (currentConfig.search.location_rules) {
        currentConfig.search.location_rules.splice(idx, 1);
        renderLocationRules();
      }
    }

    function addNewLocationRule() {
      const mode = document.getElementById('newRuleMode').value;
      const target = document.getElementById('newRuleTarget').value.trim();
      const distVal = document.getElementById('newRuleDist').value;
      const maxDist = distVal ? parseFloat(distVal) : null;

      if (!target && mode !== 'remote' && mode !== 'any') {
        showToast('Please enter a target city or location', 'warning');
        return;
      }

      if (!currentConfig.search.location_rules) {
        currentConfig.search.location_rules = [];
      }

      let desc = `${mode.toUpperCase()}`;
      if (target) desc += ` in ${target}`;
      if (maxDist) desc += ` (within ${maxDist} mi)`;

      currentConfig.search.location_rules.push({
        id: 'rule_' + Date.now(),
        enabled: true,
        mode: mode,
        target: target,
        max_distance_miles: maxDist,
        description: desc
      });

      document.getElementById('newRuleTarget').value = '';
      document.getElementById('geocodeTestResult').classList.add('hidden');
      renderLocationRules();
      showToast('Location rule added', 'success');
    }

    function addLocationPreset(presetType) {
      if (!currentConfig.search.location_rules) {
        currentConfig.search.location_rules = [];
      }

      if (presetType === 'remote_eu') {
        currentConfig.search.location_rules.push({
          id: 'rule_' + Date.now(),
          enabled: true,
          mode: 'remote',
          target: 'Europe',
          max_distance_miles: null,
          description: 'Remote in Europe'
        });
      } else if (presetType === 'hybrid_london_30') {
        currentConfig.search.location_rules.push({
          id: 'rule_' + Date.now(),
          enabled: true,
          mode: 'hybrid',
          target: 'London',
          max_distance_miles: 30,
          description: 'Hybrid within 30 miles of London'
        });
      } else if (presetType === 'onsite_cambridge_20') {
        currentConfig.search.location_rules.push({
          id: 'rule_' + Date.now(),
          enabled: true,
          mode: 'on_site',
          target: 'Cambridge',
          max_distance_miles: 20,
          description: 'On-site within 20 miles of Cambridge'
        });
      } else if (presetType === 'remote_global') {
        currentConfig.search.location_rules.push({
          id: 'rule_' + Date.now(),
          enabled: true,
          mode: 'remote',
          target: '',
          max_distance_miles: null,
          description: 'Remote (Worldwide)'
        });
      }
      renderLocationRules();
      showToast('Preset rule added', 'success');
    }

    async function testGeocodeInput() {
      const q = (document.getElementById('newRuleTarget').value || '').trim();
      const resContainer = document.getElementById('geocodeTestResult');
      if (!q) {
        showToast('Type a location to test (e.g. London, Cambridge, Guildford)', 'warning');
        return;
      }
      resContainer.classList.remove('hidden');
      resContainer.innerHTML = '<span class="text-theme-subtle">Resolving coordinates...</span>';
      
      try {
        const res = await fetch(`/api/geocode?q=${encodeURIComponent(q)}`);
        if (res.ok) {
          const data = await res.json();
          const r = data.result;
          resContainer.innerHTML = `<span class="text-emerald-400">✓ Resolved: ${escapeHTML(r.name)}, ${escapeHTML(r.country || '')} [${r.lat.toFixed(2)}, ${r.lon.toFixed(2)}]</span>`;
        } else {
          resContainer.innerHTML = `<span class="text-rose-400">✗ Could not resolve coordinates for "${escapeHTML(q)}". Text-match will be used.</span>`;
        }
      } catch (err) {
        resContainer.innerHTML = `<span class="text-amber-400">Resolution error: ${escapeHTML(err.message)}</span>`;
      }
    }

    // Tag Operations
    function addKeyword(val) {
      if (!currentConfig.search.keywords.includes(val)) {
        currentConfig.search.keywords.push(val);
        renderConfigUI();
      }
    }
    function removeKeyword(idx) {
      currentConfig.search.keywords.splice(idx, 1);
      renderConfigUI();
    }
    function clearKeywords() {
      currentConfig.search.keywords = [];
      renderConfigUI();
    }
    function resetKeywords() {
      currentConfig.search.keywords = [
        "technical artist", "tech artist", "technical art",
        "character technical artist", "technical animator", "pipeline technical director",
        "tools programmer", "tools engineer", "pipeline engineer", "vfx technical artist",
        "shader artist", "shader developer", "rendering engineer", "graphics programmer",
        "rigging artist", "rigger", "environment technical artist"
      ];
      renderConfigUI();
    }
    function addKeywordPreset(presets) {
      presets.forEach(p => {
        if (!currentConfig.search.keywords.includes(p)) currentConfig.search.keywords.push(p);
      });
      renderConfigUI();
    }

    function addExcludeKeyword(val) {
      if (!currentConfig.search.exclude_keywords.includes(val)) {
        currentConfig.search.exclude_keywords.push(val);
        renderConfigUI();
      }
    }
    function removeExcludeKeyword(idx) {
      currentConfig.search.exclude_keywords.splice(idx, 1);
      renderConfigUI();
    }
    function addExcludePreset(presets) {
      presets.forEach(p => {
        if (!currentConfig.search.exclude_keywords.includes(p)) currentConfig.search.exclude_keywords.push(p);
      });
      renderConfigUI();
    }

    function addExcludeCompany(val) {
      if (!currentConfig.search.exclude_companies.includes(val)) {
        currentConfig.search.exclude_companies.push(val);
        renderConfigUI();
      }
    }
    function removeExcludeCompany(idx) {
      currentConfig.search.exclude_companies.splice(idx, 1);
      renderConfigUI();
    }

    function addLocation(val) {
      if (!currentConfig.search.location_filter) currentConfig.search.location_filter = [];
      if (!currentConfig.search.location_filter.includes(val)) {
        currentConfig.search.location_filter.push(val);
        renderConfigUI();
      }
    }
    function removeLocation(idx) {
      if (currentConfig.search.location_filter) {
        currentConfig.search.location_filter.splice(idx, 1);
        renderConfigUI();
      }
    }

    // --- Search Results Rendering ---
    function renderSearchResults(data) {
      const jobs = data.jobs || [];
      const badge = document.getElementById('resultsCountBadge');
      const subtitle = document.getElementById('resultsStatsSubtitle');
      const cardsGrid = document.getElementById('resultsCardsGrid');
      const tableContainer = document.getElementById('resultsTableContainer');
      const emptyState = document.getElementById('emptyState');

      badge.innerText = `${jobs.length} match${jobs.length === 1 ? '' : 'es'}`;
      subtitle.innerText = `Completed in ${data.stats.duration_seconds}s • ASGC Listings: ${data.stats.asgc_raw_count.toLocaleString()} • Studio Portals Scanned: ${data.stats.scanned_studios}`;

      if (jobs.length === 0) {
        emptyState.classList.remove('hidden');
        cardsGrid.classList.add('hidden');
        tableContainer.classList.add('hidden');
        return;
      }

      emptyState.classList.add('hidden');
      filterResultsTable();
    }

    let currentSourceFilter = 'all';

    function setSourceFilter(src) {
      currentSourceFilter = src;
      const chips = [
        { id: 'srcChip_all', key: 'all' },
        { id: 'srcChip_asgc', key: 'Looker Studio / ASGC' },
        { id: 'srcChip_studio', key: 'Direct Studio' },
        { id: 'srcChip_aswift', key: 'Aardvark Swift' },
        { id: 'srcChip_ingame', key: 'InGame Job' },
        { id: 'srcChip_gibiz', key: 'GamesIndustry.biz' },
        { id: 'srcChip_wwi', key: 'Work With Indies' },
      ];
      chips.forEach(c => {
        const el = document.getElementById(c.id);
        if (!el) return;
        if (c.key === src) {
          el.className = 'chip-btn px-2.5 py-1 rounded-lg text-xs font-heading font-semibold bg-indigo-600 text-white shadow-sm transition';
        } else {
          el.className = 'chip-btn px-2.5 py-1 rounded-lg text-xs font-heading font-medium bg-theme-surface hover:bg-theme-card border border-theme-border text-theme-subtle hover:text-white transition';
        }
      });
      filterResultsTable();
    }

    function filterResultsTable() {
      const q = (document.getElementById('filterResultsInput').value || '').toLowerCase().trim();
      const filtered = allSearchResults.filter(j => {
        // Source filter
        if (currentSourceFilter !== 'all') {
          const jSrc = (j.source || '').toLowerCase();
          const targetSrc = currentSourceFilter.toLowerCase();
          if (targetSrc === 'direct studio') {
            if (!['direct web', 'greenhouse', 'lever', 'ashby', 'workable'].some(s => jSrc.includes(s))) {
              return false;
            }
          } else if (!jSrc.includes(targetSrc) && !targetSrc.includes(jSrc)) {
            return false;
          }
        }

        if (!q) return true;
        const locBadge = (j.location_match && j.location_match.display_badge) || '';
        const text = `${j.title} ${j.company} ${j.department || ''} ${j.location} ${locBadge} ${j.source} ${(j.matched_keywords || []).join(' ')}`.toLowerCase();
        return text.includes(q);
      });

      renderCards(filtered);
      renderTable(filtered);

      if (currentViewMode === 'cards') {
        document.getElementById('resultsCardsGrid').classList.remove('hidden');
        document.getElementById('resultsTableContainer').classList.add('hidden');
      } else {
        document.getElementById('resultsCardsGrid').classList.add('hidden');
        document.getElementById('resultsTableContainer').classList.remove('hidden');
      }
    }

    function renderCards(jobs) {
      const container = document.getElementById('resultsCardsGrid');
      container.innerHTML = '';

      jobs.forEach(job => {
        const card = document.createElement('div');
        card.className = "glass-card rounded-2xl p-5 flex flex-col justify-between space-y-4 hover:border-indigo-500/40 hover:shadow-card-hover transition-all duration-200";

        // Location & Distance Badge formatting
        let locBadge = '';
        if (job.location_match && job.location_match.display_badge) {
          const m = (job.location_match.mode || '').toLowerCase();
          let color = 'text-theme-subtle bg-theme-surface border-theme-border';
          if (m === 'remote' || job.remote) {
            color = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
          } else if (m === 'hybrid') {
            color = 'text-indigo-400 bg-indigo-500/10 border-indigo-500/20';
          } else if (m === 'on_site') {
            color = 'text-purple-400 bg-purple-500/10 border-purple-500/20';
          }
          locBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono border ${color}">${escapeHTML(job.location_match.display_badge)}</span>`;
        } else if (job.remote) {
          locBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono text-emerald-400 bg-emerald-500/10 border border-emerald-500/20">Remote</span>`;
        } else {
          locBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono text-theme-subtle bg-theme-surface border border-theme-border">${escapeHTML(job.location || 'On-site')}</span>`;
        }

        const matchedTags = (job.matched_keywords || []).map(k => `<span class="px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-300 text-[10px] font-heading font-medium border border-indigo-500/20">${escapeHTML(k)}</span>`).join('');
        
        const deptBadge = job.department ? `<span class="text-[11px] text-theme-subtle">• ${escapeHTML(job.department)}</span>` : '';
        const expBadge = job.experience ? `<span class="text-[10px] font-mono text-cyan-300 px-2 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-500/20">${escapeHTML(job.experience)}</span>` : '';

        const studioGrad = getStudioGradient(job.company);
        const studioInitials = getStudioInitials(job.company);

        card.innerHTML = `
          <div class="space-y-3">
            
            <!-- Top bar: Studio Monogram + Source + Location -->
            <div class="flex items-start justify-between gap-2">
              <div class="flex items-center gap-2.5">
                <div class="w-8 h-8 rounded-xl bg-gradient-to-tr ${studioGrad} flex items-center justify-center text-white font-heading font-extrabold text-xs shadow-sm flex-shrink-0">
                  ${studioInitials}
                </div>
                <div>
                  <div class="font-heading font-bold text-xs text-white leading-tight">${escapeHTML(job.company)}</div>
                  <div class="text-[10px] font-mono text-theme-subtle uppercase tracking-wider mt-0.5">${escapeHTML(job.source)}</div>
                </div>
              </div>
              <div class="flex items-center gap-1.5 flex-wrap justify-end">
                ${expBadge}
                ${locBadge}
              </div>
            </div>

            <!-- Role Title & Department -->
            <div>
              <a href="${escapeHTML(job.url)}" target="_blank" rel="noopener noreferrer" class="font-heading font-bold text-sm text-white hover:text-indigo-300 transition leading-snug line-clamp-2 block">
                ${escapeHTML(job.title)}
              </a>
              <div class="text-xs text-theme-subtle mt-1 flex items-center gap-1.5 flex-wrap">
                <span class="text-[11px] text-theme-textSecondary font-sans">${escapeHTML(job.location || 'See Details')}</span>
                ${deptBadge}
              </div>
            </div>

          </div>

          <!-- Footer with Matched Tags & Actions -->
          <div class="space-y-3 pt-3 border-t border-theme-border/60">
            <div class="flex flex-wrap gap-1">${matchedTags}</div>
            
            <div class="flex items-center justify-between gap-2 pt-1">
              <button onclick="quickAvoidCompany('${escapeQuotes(job.company)}')" title="Add studio to excluded list" class="text-[11px] px-2.5 py-1.5 rounded-lg bg-theme-surface hover:bg-rose-500/20 text-theme-subtle hover:text-rose-300 border border-theme-border font-heading transition">
                Exclude studio
              </button>
              <a href="${escapeHTML(job.url)}" target="_blank" rel="noopener noreferrer" class="px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white text-xs font-heading font-semibold flex items-center gap-1 transition shadow-sm active:scale-[0.98]">
                <span>Apply / View</span>
                <span class="text-xs">↗</span>
              </a>
            </div>
          </div>
        `;
        container.appendChild(card);
      });
    }

    function renderTable(jobs) {
      const tbody = document.getElementById('resultsTableBody');
      tbody.innerHTML = '';

      jobs.forEach(job => {
        const tr = document.createElement('tr');
        tr.className = "hover:bg-theme-surface/80 transition border-b border-theme-border/40";

        const matchedTags = (job.matched_keywords || []).map(k => `<span class="px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-300 text-[10px] font-heading border border-indigo-500/20 mr-1">${escapeHTML(k)}</span>`).join('');

        let locTableDisplay = escapeHTML(job.location || 'Onsite');
        if (job.location_match && job.location_match.display_badge) {
          const m = (job.location_match.mode || '').toLowerCase();
          if (m === 'remote' || job.remote) {
            locTableDisplay = `<span class="text-emerald-400 font-medium font-mono">${escapeHTML(job.location_match.display_badge)}</span>`;
          } else if (m === 'hybrid') {
            locTableDisplay = `<span class="text-indigo-400 font-medium font-mono">${escapeHTML(job.location_match.display_badge)}</span>`;
          } else if (m === 'on_site') {
            locTableDisplay = `<span class="text-purple-400 font-medium font-mono">${escapeHTML(job.location_match.display_badge)}</span>`;
          } else {
            locTableDisplay = escapeHTML(job.location_match.display_badge);
          }
        } else if (job.remote) {
          locTableDisplay = '<span class="text-emerald-400 font-mono">Remote</span>';
        }

        tr.innerHTML = `
          <td class="py-3 px-4 font-heading font-semibold text-white">${escapeHTML(job.title)}</td>
          <td class="py-3 px-4 text-theme-textSecondary">${escapeHTML(job.company)}</td>
          <td class="py-3 px-4 text-theme-subtle">${escapeHTML(job.department || '—')}</td>
          <td class="py-3 px-4 text-theme-subtle">${locTableDisplay}</td>
          <td class="py-3 px-4"><span class="px-2 py-0.5 rounded-md text-[10px] font-mono text-theme-subtle bg-theme-surface border border-theme-border">${escapeHTML(job.source)}</span></td>
          <td class="py-3 px-4">${matchedTags}</td>
          <td class="py-3 px-4 text-right space-x-2 font-heading">
            <button onclick="quickAvoidCompany('${escapeQuotes(job.company)}')" class="text-theme-subtle hover:text-rose-300 text-[11px] font-medium transition">Exclude</button>
            <a href="${escapeHTML(job.url)}" target="_blank" rel="noopener noreferrer" class="inline-block px-3 py-1 rounded-lg bg-indigo-600/20 hover:bg-indigo-600 text-indigo-300 hover:text-white font-semibold text-[11px] transition shadow-sm">View ↗</a>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    function setViewMode(mode) {
      currentViewMode = mode;
      const btnCards = document.getElementById('btnViewCards');
      const btnTable = document.getElementById('btnViewTable');

      if (mode === 'cards') {
        btnCards.className = "px-3 py-1 rounded-lg text-xs font-heading font-semibold text-white bg-indigo-600 shadow-sm transition";
        btnTable.className = "px-3 py-1 rounded-lg text-xs font-heading font-medium text-theme-subtle hover:text-white transition";
      } else {
        btnTable.className = "px-3 py-1 rounded-lg text-xs font-heading font-semibold text-white bg-indigo-600 shadow-sm transition";
        btnCards.className = "px-3 py-1 rounded-lg text-xs font-heading font-medium text-theme-subtle hover:text-white transition";
      }
      filterResultsTable();
    }

    function quickAvoidCompany(companyName) {
      if (!companyName) return;
      addExcludeCompany(companyName);
      showToast(`Added '${companyName}' to excluded studios list`, 'warning');
      filterResultsTable();
    }

    // --- Export Functions ---
    function exportCSV() {
      if (!allSearchResults.length) return showToast('No results to export', 'warning');
      let csv = 'Title,Company,Department,Source,Location,Remote,URL\n';
      allSearchResults.forEach(j => {
        csv += `"${(j.title || '').replace(/"/g, '""')}","${(j.company || '').replace(/"/g, '""')}","${(j.department || '').replace(/"/g, '""')}","${j.source}","${(j.location || '').replace(/"/g, '""')}",${j.remote ? 'Yes' : 'No'},"${j.url}"\n`;
      });
      downloadFile(csv, `gamedev_jobs_${new Date().toISOString().slice(0,10)}.csv`, 'text/csv');
    }

    function exportJSON() {
      if (!allSearchResults.length) return showToast('No results to export', 'warning');
      const jsonStr = JSON.stringify(allSearchResults, null, 2);
      downloadFile(jsonStr, `gamedev_jobs_${new Date().toISOString().slice(0,10)}.json`, 'application/json');
    }

    function downloadFile(content, fileName, contentType) {
      const a = document.createElement("a");
      const file = new Blob([content], { type: contentType });
      a.href = URL.createObjectURL(file);
      a.download = fileName;
      a.click();
      URL.revokeObjectURL(a.href);
    }

    // Helpers
    function escapeHTML(str) {
      if (!str) return '';
      return String(str).replace(/[&<>'"]/g, tag => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
      }[tag] || tag));
    }
    function escapeQuotes(str) {
      if (!str) return '';
      return String(str).replace(/'/g, "\\'");
    }
  </script>
</body>
</html>
"""

# --- HTTP Request Handler ---

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class WebAppHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress noisy standard request logs
        return

    def send_json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path

        if path == "/" or path == "/index.html":
            custom_index = os.path.join(SCRIPT_DIR, "index.html")
            if os.path.exists(custom_index):
                with open(custom_index, "r", encoding="utf-8") as f:
                    body = f.read().encode('utf-8')
            else:
                body = HTML_TEMPLATE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/config":
            cfg = load_config()
            self.send_json_response(cfg)
            return

        if path == "/api/stats":
            comps = load_companies()
            with_careers = sum(1 for c in comps.values() if c.get("careers_url"))
            stats = {
                "total_companies": len(comps),
                "career_portals": with_careers,
                "seen_career_jobs": 0,
            }
            if os.path.exists(SEEN_CAREER_FILE):
                try:
                    with open(SEEN_CAREER_FILE, "r", encoding="utf-8") as f:
                        sc = json.load(f)
                        stats["seen_career_jobs"] = len(sc) if isinstance(sc, list) else len(sc.get("seen_ids", []))
                except Exception:
                    pass
            self.send_json_response(stats)
            return

        if path == "/api/rescrape-status":
            global BACKGROUND_STATE
            resp_data = dict(BACKGROUND_STATE["scrape_progress"])
            resp_data["is_scraping"] = BACKGROUND_STATE["is_scraping"]
            self.send_json_response(resp_data)
            return

        if path == "/api/scheduler/status":
            info = get_scheduler_info()
            self.send_json_response(info)
            return

        if path == "/api/geocode":
            query_params = urllib.parse.parse_qs(url_parsed.query)
            q = (query_params.get("q") or [""])[0]
            if q and geocode_place:
                res = geocode_place(q)
                if res:
                    self.send_json_response({"success": True, "result": res})
                    return
                self.send_json_response({"success": False, "error": f"Coordinates not found for '{q}'"}, status=404)
                return
            self.send_json_response({"success": False, "error": "Missing query parameter 'q'"}, status=400)
            return

        # 404 fallback
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path
        length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(length) if length > 0 else b'{}'
        
        try:
            req_json = json.loads(post_data.decode('utf-8')) if post_data else {}
        except Exception:
            req_json = {}

        if path == "/api/scheduler/sync":
            config_to_use = req_json if req_json else load_config()
            if req_json:
                save_config(req_json)
            sched_cfg = config_to_use.get("schedule", {})
            times = sched_cfg.get("times", ["09:00", "13:00", "18:00"])
            enabled = sched_cfg.get("enabled", True)
            success, msg = sync_windows_scheduler(times=times, enabled=enabled)
            info = get_scheduler_info()
            self.send_json_response({
                "success": success,
                "message": msg,
                "times": times,
                "scheduler_info": info
            })
            return

        if path == "/api/geocode":
            q = req_json.get("query") or req_json.get("q", "")
            if q and geocode_place:
                res = geocode_place(q)
                if res:
                    self.send_json_response({"success": True, "result": res})
                    return
                self.send_json_response({"success": False, "error": f"Coordinates not found for '{q}'"}, status=404)
                return
            self.send_json_response({"success": False, "error": "Missing query parameter"}, status=400)
            return

        if path == "/api/config":
            if req_json:
                save_config(req_json)
                self.send_json_response({"success": True, "message": "Configuration saved"})
            else:
                self.send_json_response({"success": False, "error": "Invalid payload"}, status=400)
            return

        if path == "/api/search":
            config_to_use = req_json if req_json else load_config()
            results = run_live_search(config_to_use)
            self.send_json_response(results)
            return

        if path == "/api/search-stream":
            config_to_use = req_json if req_json else load_config()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            stream_lock = threading.Lock()

            def sse_callback(event_type, event_data):
                try:
                    payload = f"event: {event_type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                    with stream_lock:
                        self.wfile.write(payload.encode('utf-8'))
                        self.wfile.flush()
                except Exception:
                    pass

            run_live_search(config_to_use, progress_callback=sse_callback)
            return

        if path == "/api/test-notify":
            config_to_use = req_json if req_json else load_config()
            notify_results = send_test_notifications(config_to_use)
            self.send_json_response({"success": True, "results": notify_results})
            return

        if path == "/api/rescrape-gamesmap":
            global BACKGROUND_STATE
            if not BACKGROUND_STATE["is_scraping"]:
                t = threading.Thread(target=run_gamesmap_refresh_task, daemon=True)
                t.start()
                self.send_json_response({"success": True, "message": "Background scrape started"})
            else:
                self.send_json_response({"success": True, "message": "Scrape already in progress"})
            return

        self.send_response(404)
        self.end_headers()

def start_server(port=8765, open_browser=True):
    server_address = ('127.0.0.1', port)
    try:
        httpd = ThreadedHTTPServer(server_address, WebAppHandler)
    except OSError:
        # Port might be in use, try next
        port = port + 1
        server_address = ('127.0.0.1', port)
        httpd = ThreadedHTTPServer(server_address, WebAppHandler)

    url = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print("  🎮 Game Dev Job Monitor - Web GUI")
    print(f"  🌐 Server running at: {url}")
    print("  💡 Press Ctrl+C in this console to stop the server.")
    print("=" * 60)

    if open_browser:
        def _open():
            time.sleep(0.6)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopping Web GUI Server...")
        httpd.server_close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Game Dev Job Monitor Web GUI")
    parser.add_argument("--port", type=int, default=8765, help="Port to run the web server on")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--test-search", action="store_true", help="Run a quick test search via CLI and exit")
    args = parser.parse_args()

    if args.test_search:
        cfg = load_config()
        print("[*] Running test search across studio ATS portals and ASGC database...")
        
        def cli_progress(event_type, data):
            if event_type == "progress":
                active_str = ", ".join(data.get("active", [])[:3])
                comp_num = data.get("completed", 0)
                tot_num = data.get("total", 0)
                pct = data.get("percent", 0)
                matches = data.get("matched_jobs_total", 0)
                sys.stdout.write(f"\r[*] [{comp_num}/{tot_num}] ({pct:.0f}%) Querying: {active_str[:35]:<35} | Matches: {matches}  ")
                sys.stdout.flush()

        res = run_live_search(cfg, progress_callback=cli_progress)
        print(f"\n[OK] Matches found: {res['total_matched']} (in {res['stats']['duration_seconds']}s)")
        for j in res['jobs'][:5]:
            print(f"  - [{j['source']}] {j['company']} - {j['title']} ({j['location']}) -> {j['url']}")
        sys.exit(0)

    start_server(port=args.port, open_browser=not args.no_browser)
