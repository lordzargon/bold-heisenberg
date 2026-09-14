"""
Game Dev Recruiter & Specialized Job Board Harvester
Scrapes active vacancies from leading games recruiters and industry job boards:
- Aardvark Swift (aswift.com)
- InGame Job (ingamejob.com)
- GamesIndustry.biz Jobs (jobs.gamesindustry.biz)
- Work With Indies (workwithindies.com)
- Datascope (datascope.co.uk)
"""

import os
import sys
import re
import html
import json
import time
import ssl
import socket
import urllib.request
import urllib.parse
import urllib.error
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure hard global socket timeout
socket.setdefaulttimeout(10.0)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE
try:
    SSL_CTX.set_ciphers('DEFAULT:@SECLEVEL=1')
except Exception:
    pass

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
    'Connection': 'close',
}

def clean_html_text(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def parse_date_to_timestamp(date_val):
    if not date_val:
        return "", 0.0
    if isinstance(date_val, (int, float)):
        ts = float(date_val)
        if ts > 1e11:
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
        "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
        "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d/%m/%Y", "%m/%d/%Y"
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

# --- 1. Aardvark Swift ---

def fetch_aardvark_swift_jobs(max_pages=5):
    """
    Scrapes active vacancies from Aardvark Swift (aswift.com).
    """
    all_jobs = []
    seen_ids = set()

    for page in range(1, max_pages + 1):
        url = "https://www.aswift.com/jobs" if page == 1 else f"https://www.aswift.com/jobs?page={page}"
        content = None
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
                with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
                    content = resp.read().decode('utf-8', errors='replace')
                    break
            except Exception:
                time.sleep(0.4)

        if not content:
            break

        matches = list(re.finditer(r"<div class='job-title'>\s*<a href=['\"]([^'\"]+)['\"]>([^<]+)</a>\s*</div>", content))
        if not matches:
            break

        for m in matches:
            link = m.group(1).strip()
            raw_title = m.group(2).strip()
            title = clean_html_text(raw_title)
            
            slug = link.strip("/").split("/")[-1]
            job_id = f"aswift_{slug}"
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Extract location from the surrounding snippet
            loc_match = re.search(r"<li class='results-job-location'>\s*([^<]+)\s*</li>", content[m.end():m.end()+350])
            loc = clean_html_text(loc_match.group(1)) if loc_match else ""

            # Extract description snippet
            desc_match = re.search(r"<p class='job-description'>\s*(.*?)\s*</p>", content[m.end():m.end()+800], re.DOTALL)
            desc = clean_html_text(desc_match.group(1)) if desc_match else ""

            now_dt = datetime.datetime.now(datetime.timezone.utc)
            now_ts = now_dt.timestamp()
            now_disp = now_dt.strftime("%d %b %Y")
            loc_clean = loc or "UK / Hybrid / Remote"
            full_text = f"{title} {loc_clean}".lower()
            is_hybrid = "hybrid" in full_text
            is_remote = "remote" in full_text

            all_jobs.append({
                "id": job_id,
                "title": title,
                "company": "Aardvark Swift",
                "location": loc_clean,
                "hybrid": is_hybrid,
                "remote": is_remote,
                "url": full_url,
                "department": "Games Recruitment",
                "description": desc,
                "source": "Aardvark Swift",
                "date_posted": "",
                "date_posted_ts": 0.0,
                "date_added": now_disp,
                "date_added_ts": now_ts,
            })

    return all_jobs

# --- 2. InGame Job ---

def fetch_ingame_jobs(max_pages=5):
    """
    Scrapes active vacancies from InGame Job (ingamejob.com).
    """
    all_jobs = []
    seen_ids = set()

    for page in range(1, max_pages + 1):
        url = f"https://ingamejob.com/en/jobs?page={page}"
        try:
            req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=12, context=SSL_CTX) as resp:
                content = resp.read().decode('utf-8', errors='replace')
        except Exception:
            break

        blocks = content.split('<div class="listing-job-info')
        if len(blocks) <= 1:
            break

        for b in blocks[1:]:
            t_m = re.search(r'<h5>\s*<a\s+href="([^"]+)">\s*([^<]+)\s*</a>\s*</h5>', b)
            if not t_m:
                continue
            job_url = t_m.group(1).strip()
            title = clean_html_text(t_m.group(2))

            comp_m = re.search(r'la-building-o"></i>\s*([^<]+)', b)
            company = clean_html_text(comp_m.group(1)) if comp_m else "Game Studio"

            loc_m = re.search(r'la-map-marker"></i>\s*([^<]+)', b)
            location = clean_html_text(loc_m.group(1)) if loc_m else ""

            slug = job_url.rstrip("/").split("/")[-1]
            job_id = f"ingame_{slug}"
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            now_dt = datetime.datetime.now(datetime.timezone.utc)
            now_ts = now_dt.timestamp()
            now_disp = now_dt.strftime("%d %b %Y")
            loc_clean = location or "Remote / Worldwide"
            full_text = f"{title} {loc_clean}".lower()
            is_hybrid = "hybrid" in full_text
            is_remote = "remote" in full_text

            all_jobs.append({
                "id": job_id,
                "title": title,
                "company": company,
                "location": loc_clean,
                "hybrid": is_hybrid,
                "remote": is_remote,
                "url": job_url,
                "department": "InGame Job Board",
                "source": "InGame Job",
                "date_posted": "",
                "date_posted_ts": 0.0,
                "date_added": now_disp,
                "date_added_ts": now_ts,
            })

    return all_jobs

# --- 3. GamesIndustry.biz Jobs ---

def fetch_gibiz_jobs(max_pages=5):
    """
    Scrapes active vacancies from GamesIndustry.biz Jobs (jobs.gamesindustry.biz).
    """
    all_jobs = []
    seen_ids = set()

    for page in range(0, max_pages):
        url = f"https://jobs.gamesindustry.biz/jobs?page={page}" if page > 0 else "https://jobs.gamesindustry.biz/jobs"
        try:
            req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=12, context=SSL_CTX) as resp:
                content = resp.read().decode('utf-8', errors='replace')
        except Exception:
            break

        nodes = content.split('class="node node--job-per-template')
        if len(nodes) <= 1:
            matches = re.finditer(r'<a\s+[^>]*href=["\'](https://jobs\.gamesindustry\.biz/job/[^"\']+)["\'][^>]*title=["\']([^"\']+)["\']', content, re.IGNORECASE)
            for m in matches:
                job_url = m.group(1)
                title = clean_html_text(m.group(2))
                slug = job_url.rstrip("/").split("/")[-1]
                job_id = f"gibiz_{slug}"
                if job_id not in seen_ids:
                    seen_ids.add(job_id)
                    now_dt = datetime.datetime.now(datetime.timezone.utc)
                    all_jobs.append({
                        "id": job_id,
                        "title": title,
                        "company": "GamesIndustry.biz Partner",
                        "location": "UK / Europe / Remote",
                        "hybrid": "hybrid" in title.lower(),
                        "remote": True,
                        "url": job_url,
                        "department": "GamesIndustry.biz",
                        "source": "GamesIndustry.biz",
                        "date_posted": "",
                        "date_posted_ts": 0.0,
                        "date_added": now_dt.strftime("%d %b %Y"),
                        "date_added_ts": now_dt.timestamp(),
                    })
            break

        for n in nodes[1:]:
            link_m = re.search(r'<a\s+[^>]*href=["\'](https://jobs\.gamesindustry\.biz/job/[^"\']+)["\']', n)
            if not link_m:
                continue
            job_url = link_m.group(1).strip()
            
            t_m = re.search(r'title=["\']([^"\']+)["\']', n) or re.search(r'<h[234][^>]*>\s*<a[^>]*>([^<]+)</a>', n)
            title = clean_html_text(t_m.group(1)) if t_m else "Game Development Role"

            c_m = re.search(r'<picture\s+title=["\']([^"\']+)["\']', n) or re.search(r'class="job__recruiter"[^>]*>([^<]+)', n)
            company = clean_html_text(c_m.group(1)) if c_m else "GamesIndustry.biz Partner"

            loc_m = re.search(r'class="job__location"[^>]*>([^<]+)', n) or re.search(r'class="[^"]*location[^"]*"[^>]*>([^<]+)', n)
            location = clean_html_text(loc_m.group(1)) if loc_m else ""

            # Check for posted date in node snippet
            time_m = re.search(r'<time[^>]*datetime=["\']([^"\']+)["\']', n) or re.search(r'<time[^>]*>([^<]+)</time>', n)
            disp_date, ts = parse_date_to_timestamp(time_m.group(1)) if time_m else ("", 0.0)

            slug = job_url.rstrip("/").split("/")[-1]
            job_id = f"gibiz_{slug}"
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            now_dt = datetime.datetime.now(datetime.timezone.utc)
            loc_clean = location or "UK / Remote"
            full_text = f"{title} {loc_clean}".lower()
            is_hybrid = "hybrid" in full_text
            is_remote = "remote" in full_text

            all_jobs.append({
                "id": job_id,
                "title": title,
                "company": company,
                "location": loc_clean,
                "hybrid": is_hybrid,
                "remote": is_remote,
                "url": job_url,
                "department": "GamesIndustry.biz",
                "source": "GamesIndustry.biz",
                "date_posted": disp_date,
                "date_posted_ts": ts,
                "date_added": now_dt.strftime("%d %b %Y"),
                "date_added_ts": now_dt.timestamp(),
            })

    return all_jobs

# --- 4. Work With Indies ---

def fetch_workwithindies_jobs():
    """
    Scrapes active vacancies from Work With Indies (workwithindies.com).
    """
    all_jobs = []
    seen_ids = set()
    url = "https://www.workwithindies.com/"

    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=12, context=SSL_CTX) as resp:
            content = resp.read().decode('utf-8', errors='replace')
    except Exception:
        return []

    # Find full <a ... href="/careers/..." class="job-card ..."> ... </a> blocks
    for m in re.finditer(r'<a\s+[^>]*href=["\'](/careers/[^"\']+)["\'][^>]*>(.*?)</a>', content, re.DOTALL | re.IGNORECASE):
        rel_link = m.group(1).strip()
        inner_html = m.group(2)
        full_url = "https://www.workwithindies.com" + rel_link

        # Extract title from text-block-28 or text-block-14 or slug
        t_m = re.search(r'<div class="text-block-(?:28|14)">([^<]+)</div>', inner_html)
        if t_m:
            title = clean_html_text(t_m.group(1))
        else:
            # Derive from slug
            slug_parts = rel_link.strip("/").split("/")[-1].split("-")
            title = " ".join(slug_parts).title()

        # Extract company name from bold text or img alt
        comp_m = re.search(r'<div class="job-card-text bold">([^<]+)</div>', inner_html) or re.search(r'alt=["\']([^"\']+)["\']', inner_html)
        company = clean_html_text(comp_m.group(1)) if comp_m else "Indie Game Studio"

        # Extract location (often second bold text or job-card-text-smol)
        bolds = re.findall(r'<div class="job-card-text bold">([^<]+)</div>', inner_html)
        if len(bolds) > 1:
            location = clean_html_text(bolds[1])
        else:
            smol_loc = re.findall(r'<div class="job-card-text-smol">([^<]+)</div>', inner_html)
            location = clean_html_text(smol_loc[-1]) if smol_loc else "Remote"

        slug = rel_link.rstrip("/").split("/")[-1]
        job_id = f"wwi_{slug}"
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        full_text = f"{title} {location}".lower()
        is_hybrid = "hybrid" in full_text
        is_remote = "remote" in full_text or location.strip().lower() == "remote"

        all_jobs.append({
            "id": job_id,
            "title": title,
            "company": company,
            "location": location,
            "hybrid": is_hybrid,
            "remote": is_remote,
            "url": full_url,
            "department": "Indie Games",
            "source": "Work With Indies",
            "date_posted": "",
            "date_posted_ts": 0.0,
            "date_added": now_dt.strftime("%d %b %Y"),
            "date_added_ts": now_dt.timestamp(),
        })

    return all_jobs

# --- 5. Datascope & Recruiter Harvester ---

def fetch_datascope_jobs():
    """
    Attempts extraction from Datascope (datascope.co.uk).
    Gracefully handles anti-bot challenge redirects without blocking.
    """
    url = "https://datascope.co.uk/jobs/"
    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=6, context=SSL_CTX) as resp:
            content = resp.read().decode('utf-8', errors='replace')
            if "sgcaptcha" in content or resp.status == 202:
                return []
            
            jobs = []
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            for m in re.finditer(r'<a\s+[^>]*href=["\'](https://datascope\.co\.uk/job/[^"\']+|/job/[^"\']+)["\'][^>]*>(.*?)</a>', content):
                link = m.group(1)
                title = clean_html_text(m.group(2))
                if len(title) > 3 and not any(w in title.lower() for w in ["apply", "more", "view"]):
                    full_text = title.lower()
                    jobs.append({
                        "id": f"datascope_{re.sub(r'[^a-z0-9]', '', link.lower())}",
                        "title": title,
                        "company": "Datascope Recruitment",
                        "location": "UK / Remote",
                        "hybrid": "hybrid" in full_text,
                        "remote": "remote" in full_text,
                        "url": urllib.parse.urljoin(url, link),
                        "source": "Datascope",
                        "date_posted": "",
                        "date_posted_ts": 0.0,
                        "date_added": now_dt.strftime("%d %b %Y"),
                        "date_added_ts": now_dt.timestamp(),
                    })
            return jobs
    except Exception:
        return []

# --- Master Recruiter Fetcher ---

def fetch_all_recruiter_jobs(sources_config=None, progress_callback=None):
    """
    Executes all enabled recruiter & job board scrapers concurrently.
    Returns list of parsed job dicts.
    """
    if sources_config is None:
        sources_config = {
            "query_aardvark": True,
            "query_ingame": True,
            "query_gibiz": True,
            "query_workwithindies": True,
            "query_datascope": True,
        }

    tasks = {}
    if sources_config.get("query_aardvark", True):
        tasks["Aardvark Swift"] = fetch_aardvark_swift_jobs
    if sources_config.get("query_ingame", True):
        tasks["InGame Job"] = fetch_ingame_jobs
    if sources_config.get("query_gibiz", True):
        tasks["GamesIndustry.biz"] = fetch_gibiz_jobs
    if sources_config.get("query_workwithindies", True):
        tasks["Work With Indies"] = fetch_workwithindies_jobs
    if sources_config.get("query_datascope", True):
        tasks["Datascope"] = fetch_datascope_jobs

    all_recruiter_jobs = []
    if not tasks:
        return all_recruiter_jobs

    with ThreadPoolExecutor(max_workers=min(5, len(tasks))) as executor:
        future_to_name = {executor.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                jobs = future.result() or []
                all_recruiter_jobs.extend(jobs)
                if progress_callback:
                    progress_callback(name, len(jobs))
            except Exception as e:
                if progress_callback:
                    progress_callback(name, 0, str(e))

    return all_recruiter_jobs

if __name__ == "__main__":
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print("[*] Testing Recruiter & Job Board Harvesters...")
    t0 = time.time()
    
    def log_progress(name, count, err=None):
        if err:
            print(f"  [!] {name}: Failed ({err})")
        else:
            print(f"  [✓] {name}: {count} jobs retrieved")

    results = fetch_all_recruiter_jobs(progress_callback=log_progress)
    print(f"\n[OK] Total Recruiter/Job Board Roles Found: {len(results)} in {time.time()-t0:.2f}s")
    print("-" * 60)
    for j in results[:10]:
        print(f"• [{j.get('source')}] {j.get('company')} - {j.get('title')}")
        print(f"  📍 {j.get('location')} | 🔗 {j.get('url')}")
