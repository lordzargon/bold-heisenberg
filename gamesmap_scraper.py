"""
GamesMap UK Harvester & Studio Career Page Detector
Extracts all game studios/companies from GamesMap.uk with rate-limiting,
validates company websites, and discovers active careers/jobs pages.
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
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANIES_DB_FILE = os.path.join(SCRIPT_DIR, "companies.json")
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "gamesmap_progress.json")

BASE_URL = "https://app.gamesmap.uk/organisations/?activities=publisher&activities=developer&activities=other&inactive=false&view=list"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# SSL context that doesn't fail on self-signed / incomplete chains when verifying studio sites
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

PARKED_DOMAIN_TERMS = [
    "hugedomains.com",
    "buydomainnames.co.uk",
    "dan.com",
    "sedo.com",
    "afternic.com",
    "godaddy.com",
    "domainmarket.com",
    "namecheap.com",
    "parkingcrew.net",
    "bodis.com",
    "undeveloped.com",
    "domainmanage.com",
    "buydomains.com",
    "domain-for-sale",
    "buy this domain",
    "domain-sold.php",
    "squadhelp.com",
    "atom.com",
    "uniregistry.com",
    "brandbucket.com",
    "domain is for sale",
    "this domain may be for sale",
]

CAREER_PATH_CANDIDATES = [
    "/careers",
    "/careers/",
    "/jobs",
    "/jobs/",
    "/join-us",
    "/join-us/",
    "/join",
    "/join/",
    "/work-with-us",
    "/work-with-us/",
    "/vacancies",
    "/vacancies/",
    "/come-join-us",
    "/come-join-us/",
    "/careers.html",
    "/jobs.html",
    "/join.html",
    "/vacancies.html",
    "/working-here",
    "/working-here/",
    "/opportunities",
    "/opportunities/",
    "/about/careers",
    "/about/jobs",
    "/open-roles",
    "/open-positions",
]

ATS_DOMAINS = [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "apply.workable.com",
    "teamtailor.com",
    "jobs.ashbyhq.com",
    "bamboohr.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "pinpointhq.com",
    "recruitee.com",
    "personio.de",
    "personio.com",
    "breezy.hr",
    "workable.com",
    "jobvite.com",
    "talos360",
]

def get_polite_headers(referer=None):
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    return headers

def safe_request(url, headers=None, timeout=10, max_retries=3, backoff_base=2.0):
    """
    Polite HTTP request wrapper with exponential backoff on 429/503/errors.
    """
    if headers is None:
        headers = get_polite_headers()
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as response:
                content = response.read()
                # Try UTF-8 first, fallback to latin-1
                try:
                    text = content.decode('utf-8')
                except UnicodeDecodeError:
                    text = content.decode('latin-1', errors='replace')
                return {
                    "status": response.status,
                    "url": response.geturl(),
                    "headers": dict(response.headers),
                    "text": text,
                    "error": None
                }
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 502):
                sleep_time = (backoff_base ** attempt) + random.uniform(0.5, 1.5)
                print(f"[!] HTTP {e.code} for {url}. Backing off for {sleep_time:.2f}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(sleep_time)
            elif e.code in (404, 403, 410):
                return {"status": e.code, "url": url, "headers": {}, "text": "", "error": f"HTTP {e.code}"}
            else:
                if attempt == max_retries - 1:
                    return {"status": e.code, "url": url, "headers": {}, "text": "", "error": str(e)}
                time.sleep(1.0)
        except Exception as e:
            if attempt == max_retries - 1:
                return {"status": 0, "url": url, "headers": {}, "text": "", "error": str(e)}
            time.sleep(1.0 + random.uniform(0.2, 0.8))
            
    return {"status": 0, "url": url, "headers": {}, "text": "", "error": "Max retries exceeded"}

def load_companies_db():
    if os.path.exists(COMPANIES_DB_FILE):
        try:
            with open(COMPANIES_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Warning reading companies DB: {e}")
    return {}

def save_companies_db(companies_dict):
    tmp_file = COMPANIES_DB_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(companies_dict, f, indent=2, ensure_ascii=False)
    if os.path.exists(COMPANIES_DB_FILE):
        try:
            os.replace(tmp_file, COMPANIES_DB_FILE)
        except OSError:
            os.remove(COMPANIES_DB_FILE)
            os.rename(tmp_file, COMPANIES_DB_FILE)
    else:
        os.rename(tmp_file, COMPANIES_DB_FILE)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_scraped_page": 0, "total_pages": None, "completed": False}

def save_progress(progress_data):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, indent=2)

def parse_gamesmap_page(html):
    """
    Extracts all companies listed on a GamesMap organisations page.
    """
    companies = []
    item_blocks = re.findall(r'<div class="organisations-list-item[^"]*"[^>]*>(.*?)</div>\s*(?=<div class="organisations-list-item|$)', html, re.DOTALL)
    
    if not item_blocks:
        link_matches = re.findall(r'<a\s+href="(/organisations/([0-9a-fA-F-]+)/[^"]*)"\s+class="organisations-list-item__name-link"[^>]*>.*?<span class="organisations-list-item__title">(.*?)</span>', html, re.DOTALL)
        for rel_url, guid, title in link_matches:
            companies.append({
                "id": guid,
                "name": title.strip(),
                "gamesmap_url": f"https://app.gamesmap.uk/organisations/{guid}/",
                "company_number": "",
                "activities": ["Developer/Publisher"],
                "ukie_member": False,
            })
        return companies

    for block in item_blocks:
        link_m = re.search(r'href="(/organisations/([0-9a-fA-F-]+)/[^"]*)"', block)
        title_m = re.search(r'class="organisations-list-item__title">([^<]+)<', block)
        if not link_m or not title_m:
            continue
        
        guid = link_m.group(2)
        name = title_m.group(1).strip()
        
        # Check company number
        comp_num_m = re.search(r'company/([0-9A-Za-z]+)', block)
        comp_num = comp_num_m.group(1) if comp_num_m else ""
        
        # Check Ukie membership
        ukie_member = "Ukie member" in block
        
        # Check activities
        act_m = re.search(r'organisations-list-item__activity.*?organisations-list-item__meta-value">(.*?)</div>', block, re.DOTALL)
        activities = []
        if act_m:
            act_text = re.sub(r'<[^>]+>', '', act_m.group(1)).replace('+', ',')
            activities = [a.strip() for a in act_text.split(',') if a.strip()]
        
        companies.append({
            "id": guid,
            "name": name,
            "gamesmap_url": f"https://app.gamesmap.uk/organisations/{guid}/",
            "company_number": comp_num,
            "activities": activities,
            "ukie_member": ukie_member,
        })
        
    return companies

def scrape_gamesmap(max_pages=None, min_delay=0.6, max_delay=1.2):
    """
    Crawls GamesMap UK with polite rate-limiting and jitter.
    """
    companies_db = load_companies_db()
    progress = load_progress()
    start_page = progress.get("last_scraped_page", 0) + 1
    
    if progress.get("completed", False) and not max_pages:
        print(f"[*] GamesMap UK scrape was previously completed ({len(companies_db)} companies loaded).")
        return companies_db
        
    print(f"[*] Starting GamesMap UK harvest from page {start_page}...")
    page = start_page
    
    while True:
        if max_pages and (page - start_page + 1) > max_pages:
            print(f"[*] Reached page limit ({max_pages} pages).")
            break
            
        page_url = f"{BASE_URL}&page={page}"
        print(f"[{page}] Fetching {page_url}...")
        
        resp = safe_request(page_url, timeout=15)
        if resp["status"] == 404 or not resp["text"]:
            print(f"[*] Reached end of pagination at page {page-1}.")
            progress["completed"] = True
            save_progress(progress)
            break
            
        page_companies = parse_gamesmap_page(resp["text"])
        if not page_companies:
            print(f"[*] No companies parsed on page {page}. Ending pagination.")
            progress["completed"] = True
            save_progress(progress)
            break
            
        # Add / update companies in db
        new_count = 0
        for comp in page_companies:
            cid = comp["id"]
            if cid not in companies_db:
                companies_db[cid] = {
                    **comp,
                    "website_url": None,
                    "website_status": None,
                    "careers_url": None,
                    "careers_type": None,
                    "last_checked": None,
                }
                new_count += 1
            else:
                # Update metadata if missing
                for k in ["company_number", "activities", "ukie_member", "name"]:
                    if comp.get(k) and not companies_db[cid].get(k):
                        companies_db[cid][k] = comp[k]
                        
        print(f"    Page {page}: found {len(page_companies)} companies ({new_count} new, total DB: {len(companies_db)}).")
        
        progress["last_scraped_page"] = page
        save_progress(progress)
        save_companies_db(companies_db)
        
        # Check if "Next" link exists
        if 'Next <i class="fas fa-arrow-right"></i>' not in resp["text"]:
            print(f"[*] No 'Next' button on page {page}. Completed scrape.")
            progress["completed"] = True
            save_progress(progress)
            break
            
        page += 1
        
        # Polite jitter delay to prevent throttling
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)
        
    return companies_db

def generate_domain_candidates(company_name):
    """
    Generates high-probability domain candidates for a given company name.
    """
    clean = re.sub(r'[^a-zA-Z0-9\s]', '', company_name).lower()
    words = clean.split()
    if not words:
        return []
    
    combos = []
    joined = "".join(words)
    hyphenated = "-".join(words)
    
    filtered_words = [w for w in words if w not in ("ltd", "limited", "plc", "llc", "corp", "inc", "uk")]
    f_joined = "".join(filtered_words)
    f_hyphen = "-".join(filtered_words)
    
    base_names = list(dict.fromkeys([joined, hyphenated, f_joined, f_hyphen]))
    
    # Add common extensions
    for b in base_names:
        if len(b) >= 2:
            combos.append(f"https://www.{b}.co.uk")
            combos.append(f"https://www.{b}.com")
            combos.append(f"https://{b}.games")
            combos.append(f"https://{b}.io")
            combos.append(f"https://{b}.gg")
            combos.append(f"https://{b}.co")
            combos.append(f"https://{b}.uk")
            
    return list(dict.fromkeys(combos))

def check_website_alive(url, timeout=6):
    """
    Verifies if a website is reachable and returns the resolved URL.
    Filters out parked domain sales and dead redirects.
    """
    try:
        req = urllib.request.Request(url, headers=get_polite_headers(url))
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            if resp.status < 400:
                final_url = resp.geturl().lower()
                # Check if final redirect is a domain parking service
                if any(p in final_url for p in PARKED_DOMAIN_TERMS):
                    return False, None
                
                # Check snippet of body if parked
                body_sample = resp.read(2048).decode('utf-8', errors='ignore').lower()
                if any(p in body_sample for p in ["buy this domain", "domain is for sale", "parked domain", "hugedomains"]):
                    return False, None
                    
                return True, resp.geturl()
    except Exception:
        pass
    return False, None

def find_careers_page_on_site(homepage_url, html_content=None):
    """
    Inspects homepage HTML and common career URL routes to discover jobs/careers page.
    """
    if not html_content:
        resp = safe_request(homepage_url, timeout=8)
        if resp["status"] != 200 or not resp["text"]:
            return None, None
        html_content = resp["text"]
        homepage_url = resp["url"]
        
    parsed_base = urllib.parse.urlparse(homepage_url)
    domain = parsed_base.netloc.lower()
    base_root = f"{parsed_base.scheme}://{parsed_base.netloc}"

    # 1. Look for direct links to known ATS platforms (Greenhouse, Lever, Workable, etc.)
    for ats in ATS_DOMAINS:
        ats_matches = re.findall(rf'href=["\'](https?://[^"\']*{re.escape(ats)}[^"\']*)["\']', html_content, re.IGNORECASE)
        if ats_matches:
            return ats_matches[0], ats.split('.')[0]

    # 2. Look for links with career-related text or href in the HTML
    link_tags = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_content, re.DOTALL | re.IGNORECASE)
    
    career_keywords = [
        "career", "careers", "jobs", "job", "join us", "join our team", 
        "work with us", "vacancies", "we are hiring", "hiring", "open positions", "opportunities"
    ]
    
    for href, text in link_tags:
        clean_text = re.sub(r'<[^>]+>', '', text).strip().lower()
        href_lower = href.lower()
        
        is_career_match = any(kw in clean_text for kw in career_keywords) or any(f"/{kw}" in href_lower for kw in ["career", "careers", "jobs", "vacancies", "join-us", "work-with-us", "openings"])
        
        if is_career_match:
            full_career_url = urllib.parse.urljoin(homepage_url, href)
            if full_career_url.startswith("http") and domain in full_career_url.lower():
                return full_career_url, "custom_html"
            elif any(ats in full_career_url for ats in ATS_DOMAINS):
                return full_career_url, "ats_embed"

    # 3. Test common standard paths (/careers, /jobs, /join-us)
    for path in CAREER_PATH_CANDIDATES:
        candidate_url = f"{base_root}{path}"
        try:
            resp = safe_request(candidate_url, timeout=5)
            if resp["status"] == 200 and resp["text"]:
                t = resp["text"].lower()
                final_u = resp["url"].lower()
                if not any(p in final_u for p in PARKED_DOMAIN_TERMS):
                    if any(w in t for w in ["open roles", "open positions", "apply", "job", "career", "join our team", "vacancies", "we are hiring", "speculative"]):
                        return resp["url"], "direct_path"
        except Exception:
            pass

    # 4. Test common subdomains (careers.domain, jobs.domain)
    root_domain = domain[4:] if domain.startswith("www.") else domain
    for sub in ["careers", "jobs"]:
        cand_sub = f"https://{sub}.{root_domain}"
        try:
            resp = safe_request(cand_sub, timeout=5)
            if resp["status"] == 200 and resp["text"]:
                t = resp["text"].lower()
                final_u = resp["url"].lower()
                if not any(p in final_u for p in PARKED_DOMAIN_TERMS):
                    if any(w in t for w in ["open roles", "open positions", "apply", "job", "career", "vacancies", "join our team", "we are hiring"]):
                        return resp["url"], "subdomain"
        except Exception:
            pass

    return None, None

def verify_and_enrich_company(comp):
    """
    Enriches a company record with website and career page data.
    """
    name = comp["name"]
    guid = comp["id"]
    
    if comp.get("careers_url") and comp.get("website_status") == 200:
        return comp

    detail_url = f"https://app.gamesmap.uk/organisations/{guid}/"
    detail_resp = safe_request(detail_url, timeout=8)
    
    found_website = comp.get("website_url")
    
    if not found_website and detail_resp["text"]:
        ext_links = re.findall(r'href=["\'](https?://[^"\']+)["\']', detail_resp["text"])
        for l in ext_links:
            if not any(x in l for x in ['gamesmap', 'ukie', 'facebook', 'twitter', 'linkedin', 'instagram', 'twitch', 'youtube', 'companies-information', 'cloudflare', 'gov.uk']):
                is_alive, resolved = check_website_alive(l)
                if is_alive:
                    found_website = resolved
                    break

    if not found_website:
        candidates = generate_domain_candidates(name)
        for cand in candidates[:6]:
            is_alive, resolved = check_website_alive(cand, timeout=4)
            if is_alive:
                found_website = resolved
                break

    comp["website_url"] = found_website
    comp["website_status"] = 200 if found_website else None

    if found_website:
        career_url, career_type = find_careers_page_on_site(found_website)
        comp["careers_url"] = career_url
        comp["careers_type"] = career_type
    else:
        comp["careers_url"] = None
        comp["careers_type"] = None
        
    comp["last_checked"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return comp

def enrich_all_companies(companies_db, max_workers=6, max_companies=None):
    """
    Verifies websites and finds career pages concurrently with rate limiting.
    """
    to_process = [c for c in companies_db.values() if not c.get("last_checked") or not c.get("website_url")]
    if max_companies:
        to_process = to_process[:max_companies]
        
    print(f"[*] Enriching {len(to_process)} companies with websites & career pages (Workers: {max_workers})...")
    
    completed_count = 0
    careers_found = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {executor.submit(verify_and_enrich_company, comp): comp["id"] for comp in to_process}
        
        for future in as_completed(future_to_id):
            cid = future_to_id[future]
            try:
                updated_comp = future.result()
                companies_db[cid] = updated_comp
                completed_count += 1
                
                if updated_comp.get("careers_url"):
                    careers_found += 1
                    print(f"  [+] ({completed_count}/{len(to_process)}) Found Careers for '{updated_comp['name']}': {updated_comp['careers_url']} ({updated_comp.get('careers_type')})")
                elif updated_comp.get("website_url"):
                    print(f"  [~] ({completed_count}/{len(to_process)}) Working site for '{updated_comp['name']}': {updated_comp['website_url']}")
                else:
                    if completed_count % 20 == 0:
                        print(f"  [-] ({completed_count}/{len(to_process)}) Processed... Total Careers Found So Far: {careers_found}")
                        
                if completed_count % 10 == 0:
                    save_companies_db(companies_db)
                    
            except Exception as e:
                print(f"[!] Error processing {cid}: {e}")
                
    save_companies_db(companies_db)
    print(f"[✓] Completed enrichment. Total studios with careers pages: {len([c for c in companies_db.values() if c.get('careers_url')])}/{len(companies_db)}")
    return companies_db

def enrich_existing_companies(companies_db=None, max_workers=6, max_companies=None):
    """
    Enriches existing companies in the database with websites and career pages.
    If companies_db is not provided, loads from companies.json.
    """
    if companies_db is None:
        companies_db = load_companies_db()
    return enrich_all_companies(companies_db, max_workers=max_workers, max_companies=max_companies)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GamesMap UK Studio Harvester & Career Detector")
    parser.add_argument("--pages", type=int, default=None, help="Number of pages to scrape (default: all)")
    parser.add_argument("--enrich", action="store_true", help="Run website and careers page detection on stored companies")
    parser.add_argument("--max-enrich", type=int, default=None, help="Maximum number of companies to enrich")
    parser.add_argument("--workers", type=int, default=6, help="Worker threads for website checking (default: 6)")
    parser.add_argument("--status", action="store_true", help="Print current status of companies database")
    
    args = parser.parse_args()
    
    if args.status:
        db = load_companies_db()
        prog = load_progress()
        with_sites = [c for c in db.values() if c.get("website_url")]
        with_careers = [c for c in db.values() if c.get("careers_url")]
        print("="*60)
        print("GamesMap UK Harvester Status")
        print("="*60)
        print(f"Total Companies in Database: {len(db)}")
        print(f"Last Scraped Page:           {prog.get('last_scraped_page', 0)}")
        print(f"Scrape Completed:            {prog.get('completed', False)}")
        print(f"Working Websites Discovered: {len(with_sites)}")
        print(f"Active Career Pages Found:   {len(with_careers)}")
        print("="*60)
        sys.exit(0)
        
    db = scrape_gamesmap(max_pages=args.pages)
    
    if args.enrich or args.pages is not None:
        enrich_all_companies(db, max_workers=args.workers, max_companies=args.max_enrich)
