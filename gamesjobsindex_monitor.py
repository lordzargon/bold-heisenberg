"""
Games Jobs Index Harvester
Fetches live game developer postings across 1,200+ studios from https://gamesjobsindex.com/
"""

import os
import sys
import json
import gzip
import time
import ssl
import socket
import datetime
import urllib.request
import urllib.error

# Ensure hard global socket timeout
socket.setdefaulttimeout(15.0)

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

GJI_FEED_URL = "https://gamesjobsindex.com/jobs.json"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Encoding': 'gzip',
    'Referer': 'https://gamesjobsindex.com/',
}

try:
    from date_utils import parse_date_to_timestamp
except ImportError:
    def parse_date_to_timestamp(d):
        return str(d)[:10], 0.0

def parse_iso_to_timestamp(date_str):
    return parse_date_to_timestamp(date_str)

def fetch_gamesjobsindex_jobs(sources_config=None, progress_callback=None):
    """
    Fetches and parses the live structured jobs feed from gamesjobsindex.com.
    Returns a list of standardized job dictionaries.
    """
    if sources_config is not None and not sources_config.get("query_gamesjobsindex", True):
        return []

    req = urllib.request.Request(GJI_FEED_URL, headers=DEFAULT_HEADERS)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            content = resp.read()
            enc = resp.info().get('Content-Encoding')
            if enc == 'gzip' or (len(content) > 2 and content[:2] == b'\x1f\x8b'):
                content = gzip.decompress(content)
            data = json.loads(content.decode('utf-8', errors='replace'))

        records = data.get("records", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        now_ts = now_dt.timestamp()
        now_disp = now_dt.strftime("%d %b %Y")

        parsed_jobs = []
        for r in records:
            title = (r.get("title") or "").strip()
            company = (r.get("company") or "").strip()
            url = (r.get("source_url") or "").strip()
            if not title or not company:
                continue

            raw_id = str(r.get("id") or "").strip()
            job_id = f"gji_{raw_id}" if raw_id else f"gji_{company.lower()}_{title.lower()}"

            loc = (r.get("location") or "").strip()
            country = (r.get("country") or "").strip()
            workplace = (r.get("workplace") or "").strip().lower()
            remote_val = bool(r.get("remote", False))
            
            # Refine location text if country is provided
            loc_disp = loc
            if country and country not in loc_disp:
                loc_disp = f"{loc_disp}, {country}" if loc_disp else country

            is_hybrid = "hybrid" in loc.lower() or "hybrid" in workplace
            is_remote = remote_val or "remote" in loc.lower() or "remote" in workplace

            disp_date, ts = parse_iso_to_timestamp(r.get("posted_at") or r.get("first_seen"))
            dept = (r.get("department") or r.get("category") or "").strip()
            desc = (r.get("description_snippet") or "").strip()
            salary = (r.get("salary_text") or "").strip()

            parsed_jobs.append({
                "id": job_id,
                "title": title,
                "company": company,
                "location": loc_disp or "Worldwide",
                "country": country,
                "hybrid": is_hybrid,
                "remote": is_remote,
                "url": url or f"https://gamesjobsindex.com/",
                "department": dept,
                "description": desc,
                "salary": salary,
                "source": "Games Jobs Index",
                "source_ats": r.get("source_ats", ""),
                "date_posted": disp_date,
                "date_posted_ts": ts,
                "date_added": now_disp,
                "date_added_ts": now_ts,
            })

        if progress_callback:
            progress_callback("Games Jobs Index", len(parsed_jobs))

        return parsed_jobs

    except Exception as e:
        if progress_callback:
            progress_callback("Games Jobs Index", 0, str(e))
        return []

if __name__ == "__main__":
    print("[*] Fetching live feed from Games Jobs Index (https://gamesjobsindex.com/)...")
    t_start = time.time()
    def _cb(name, count, err=None):
        if err:
            print(f"  [!] {name}: Failed ({err})")
        else:
            print(f"  [✓] {name}: {count:,} jobs loaded in {time.time()-t_start:.2f}s")

    jobs = fetch_gamesjobsindex_jobs(progress_callback=_cb)
    print(f"\n[OK] Retrieved {len(jobs):,} standardized jobs across studios.")
    print("-" * 75)
    for j in jobs[:10]:
        print(f"• [{j.get('company')}] {j.get('title')}")
        print(f"  📍 {j.get('location')} | Remote: {j.get('remote')} | ATS: {j.get('source_ats')}")
        print(f"  🔗 {j.get('url')}")
