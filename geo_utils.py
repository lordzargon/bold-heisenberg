"""
Geocoding, Distance Calculation, and Multi-Rule Location Filtering Engine
Pure Python standard library - Zero external dependencies.
"""

import os
import re
import json
import math
import ssl
import time
import threading
import urllib.request
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "location_cache.json")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    'User-Agent': 'GameDevJobMonitor/2.0 (LocationFilter; contact@gamedevjobs.local)',
    'Accept': 'application/json, text/html, */*'
}

# Pre-seeded popular game dev hubs (Coordinates + Country) to guarantee instant lookups
PRESEEDED_LOCATIONS = {
    "london": {"name": "London", "lat": 51.5074, "lon": -0.1278, "country": "United Kingdom", "country_code": "GB"},
    "london, uk": {"name": "London", "lat": 51.5074, "lon": -0.1278, "country": "United Kingdom", "country_code": "GB"},
    "london, united kingdom": {"name": "London", "lat": 51.5074, "lon": -0.1278, "country": "United Kingdom", "country_code": "GB"},
    "cambridge": {"name": "Cambridge", "lat": 52.2053, "lon": 0.1218, "country": "United Kingdom", "country_code": "GB"},
    "cambridge, uk": {"name": "Cambridge", "lat": 52.2053, "lon": 0.1218, "country": "United Kingdom", "country_code": "GB"},
    "ely": {"name": "Ely", "lat": 52.3990, "lon": 0.2620, "country": "United Kingdom", "country_code": "GB"},
    "ely, cambridgeshire": {"name": "Ely, Cambridgeshire", "lat": 52.3990, "lon": 0.2620, "country": "United Kingdom", "country_code": "GB"},
    "ely, uk": {"name": "Ely", "lat": 52.3990, "lon": 0.2620, "country": "United Kingdom", "country_code": "GB"},
    "peterborough": {"name": "Peterborough", "lat": 52.5726, "lon": -0.2427, "country": "United Kingdom", "country_code": "GB"},
    "newmarket": {"name": "Newmarket", "lat": 52.2454, "lon": 0.4074, "country": "United Kingdom", "country_code": "GB"},
    "huntingdon": {"name": "Huntingdon", "lat": 52.3312, "lon": -0.1834, "country": "United Kingdom", "country_code": "GB"},
    "bury st edmunds": {"name": "Bury St Edmunds", "lat": 52.2474, "lon": 0.7183, "country": "United Kingdom", "country_code": "GB"},
    "norwich": {"name": "Norwich", "lat": 52.6309, "lon": 1.2974, "country": "United Kingdom", "country_code": "GB"},
    "ipswich": {"name": "Ipswich", "lat": 52.0567, "lon": 1.1482, "country": "United Kingdom", "country_code": "GB"},
    "guildford": {"name": "Guildford", "lat": 51.2362, "lon": -0.5704, "country": "United Kingdom", "country_code": "GB"},
    "guildford, uk": {"name": "Guildford", "lat": 51.2362, "lon": -0.5704, "country": "United Kingdom", "country_code": "GB"},
    "brighton": {"name": "Brighton", "lat": 50.8225, "lon": -0.1372, "country": "United Kingdom", "country_code": "GB"},
    "bristol": {"name": "Bristol", "lat": 51.4545, "lon": -2.5879, "country": "United Kingdom", "country_code": "GB"},
    "leamington spa": {"name": "Leamington Spa", "lat": 52.2852, "lon": -1.5200, "country": "United Kingdom", "country_code": "GB"},
    "royal leamington spa": {"name": "Royal Leamington Spa", "lat": 52.2852, "lon": -1.5200, "country": "United Kingdom", "country_code": "GB"},
    "oxford": {"name": "Oxford", "lat": 51.7520, "lon": -1.2577, "country": "United Kingdom", "country_code": "GB"},
    "edinburgh": {"name": "Edinburgh", "lat": 55.9533, "lon": -3.1883, "country": "United Kingdom", "country_code": "GB"},
    "manchester": {"name": "Manchester", "lat": 53.4808, "lon": -2.2426, "country": "United Kingdom", "country_code": "GB"},
    "sheffield": {"name": "Sheffield", "lat": 53.3811, "lon": -1.4701, "country": "United Kingdom", "country_code": "GB"},
    "leeds": {"name": "Leeds", "lat": 53.8008, "lon": -1.5491, "country": "United Kingdom", "country_code": "GB"},
    "newcastle": {"name": "Newcastle upon Tyne", "lat": 54.9783, "lon": -1.6178, "country": "United Kingdom", "country_code": "GB"},
    "birmingham": {"name": "Birmingham", "lat": 52.4862, "lon": -1.8904, "country": "United Kingdom", "country_code": "GB"},
    "liverpool": {"name": "Liverpool", "lat": 53.4084, "lon": -2.9916, "country": "United Kingdom", "country_code": "GB"},
    "cardiff": {"name": "Cardiff", "lat": 51.4816, "lon": -3.1791, "country": "United Kingdom", "country_code": "GB"},
    "belfast": {"name": "Belfast", "lat": 54.5973, "lon": -5.9301, "country": "United Kingdom", "country_code": "GB"},
    "dublin": {"name": "Dublin", "lat": 53.3498, "lon": -6.2603, "country": "Ireland", "country_code": "IE"},
    "paris": {"name": "Paris", "lat": 48.8566, "lon": 2.3522, "country": "France", "country_code": "FR"},
    "berlin": {"name": "Berlin", "lat": 52.5200, "lon": 13.4050, "country": "Germany", "country_code": "DE"},
    "munich": {"name": "Munich", "lat": 48.1351, "lon": 11.5820, "country": "Germany", "country_code": "DE"},
    "stockholm": {"name": "Stockholm", "lat": 59.3293, "lon": 18.0686, "country": "Sweden", "country_code": "SE"},
    "helsinki": {"name": "Helsinki", "lat": 60.1699, "lon": 24.9384, "country": "Finland", "country_code": "FI"},
    "copenhagen": {"name": "Copenhagen", "lat": 55.6761, "lon": 12.5683, "country": "Denmark", "country_code": "DK"},
    "amsterdam": {"name": "Amsterdam", "lat": 52.3676, "lon": 4.9041, "country": "Netherlands", "country_code": "NL"},
    "barcelona": {"name": "Barcelona", "lat": 41.3879, "lon": 2.1699, "country": "Spain", "country_code": "ES"},
    "madrid": {"name": "Madrid", "lat": 40.4168, "lon": -3.7038, "country": "Spain", "country_code": "ES"},
    "warsaw": {"name": "Warsaw", "lat": 52.2297, "lon": 21.0122, "country": "Poland", "country_code": "PL"},
    "krakow": {"name": "Krakow", "lat": 50.0647, "lon": 19.9450, "country": "Poland", "country_code": "PL"},
    "oslo": {"name": "Oslo", "lat": 59.9139, "lon": 10.7522, "country": "Norway", "country_code": "NO"},
    "vienna": {"name": "Vienna", "lat": 48.2082, "lon": 16.3738, "country": "Austria", "country_code": "AT"},
    "zurich": {"name": "Zurich", "lat": 47.3769, "lon": 8.5417, "country": "Switzerland", "country_code": "CH"},
}

EUROPE_COUNTRY_CODES = {
    "GB", "UK", "FR", "DE", "ES", "IT", "SE", "NO", "FI", "DK", "NL", "BE", 
    "IE", "PL", "CZ", "AT", "CH", "PT", "RO", "GR", "HU", "BG", "HR", "SK", 
    "SI", "EE", "LV", "LT", "LU", "MT", "CY", "IS", "UA", "RS", "BA", "ME", 
    "MK", "AL"
}

EUROPE_COUNTRY_NAMES = {
    "united kingdom", "uk", "great britain", "england", "scotland", "wales", "northern ireland",
    "germany", "france", "spain", "italy", "sweden", "norway", "finland", "denmark",
    "netherlands", "belgium", "ireland", "poland", "czech republic", "czechia", "austria",
    "switzerland", "portugal", "greece", "hungary", "romania", "bulgaria", "croatia",
    "slovakia", "slovenia", "estonia", "latvia", "lithuania", "luxembourg", "malta",
    "cyprus", "iceland", "ukraine", "serbia", "europe", "emea", "eu", "eea"
}

NORTH_AMERICA_NAMES = {
    "united states", "usa", "us", "canada", "mexico", "north america"
}

UK_POSTCODE_REGEX = re.compile(r'^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})?$', re.IGNORECASE)

# --- In-Memory & Persistent Cache ---
_CACHE = None
_CACHE_LOCK = threading.Lock()

def _load_cache():
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is not None:
            return _CACHE
        
        _CACHE = dict(PRESEEDED_LOCATIONS)
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    disk_cache = json.load(f)
                    for k, v in disk_cache.items():
                        # Sanitize any previous faulty entries (e.g. UK -> Russia or Ely -> US)
                        if v is not None:
                            if k in ["uk", "united kingdom", "gb"] and v.get("country_code") != "GB":
                                continue
                            if k in ["ely", "ely, cambridgeshire"] and v.get("country_code") != "GB":
                                continue
                        _CACHE[k] = v
            except Exception:
                pass
        return _CACHE

def _save_cache():
    global _CACHE
    if _CACHE is None:
        return
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_CACHE, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# --- Distance Calculation ---

def haversine_distance(lat1, lon1, lat2, lon2, unit="miles"):
    """
    Computes Great-Circle distance between two GPS coordinates using the Haversine formula.
    Returns distance in miles (default) or kilometers.
    """
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (ValueError, TypeError):
        return None

    # Radius of Earth
    r = 3958.8 if unit == "miles" else 6371.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c

# --- Geocoding Engine ---

def geocode_uk_postcode(query):
    """
    Geocodes UK postcodes and outcodes (e.g. 'CB7 4DL', 'CB7', 'SW1A 1AA', 'GU1')
    via the official open postcodes.io API.
    """
    clean_pc = query.strip().upper()
    if not UK_POSTCODE_REGEX.match(clean_pc):
        return None

    # 1. Try full postcode
    try:
        encoded = urllib.parse.quote(clean_pc)
        url = f"https://api.postcodes.io/postcodes/{encoded}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=3, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            res = data.get("result", {})
            if res and res.get("latitude") and res.get("longitude"):
                admin = res.get("admin_district") or res.get("admin_county") or ""
                name = f"{res.get('postcode')} ({admin})" if admin else res.get("postcode")
                return {
                    "name": name,
                    "lat": float(res.get("latitude")),
                    "lon": float(res.get("longitude")),
                    "country": "United Kingdom",
                    "country_code": "GB"
                }
    except Exception:
        pass

    # 2. Try outward postcode code (e.g. 'CB7', 'GU1', 'SW1')
    try:
        encoded = urllib.parse.quote(clean_pc)
        url = f"https://api.postcodes.io/outcodes/{encoded}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=3, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            res = data.get("result", {})
            if res and res.get("latitude") and res.get("longitude"):
                admin = res.get("admin_district", [])
                admin_str = admin[0] if isinstance(admin, list) and admin else str(admin or "")
                name = f"{res.get('outcode')} ({admin_str})" if admin_str else res.get("outcode")
                return {
                    "name": name,
                    "lat": float(res.get("latitude")),
                    "lon": float(res.get("longitude")),
                    "country": "United Kingdom",
                    "country_code": "GB"
                }
    except Exception:
        pass

    return None

def geocode_photon(query):
    """
    Geocodes a place name via Photon (OpenStreetMap data with global coverage & county parsing).
    """
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://photon.komoot.io/api/?q={encoded}&limit=5"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=4, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            features = data.get("features", [])
            if features:
                # Prefer UK / exact match if available
                chosen = features[0]
                for f in features:
                    props = f.get("properties", {})
                    cc = (props.get("countrycode") or "").upper()
                    if cc in ["GB", "UK"]:
                        chosen = f
                        break
                p = chosen.get("properties", {})
                coords = chosen.get("geometry", {}).get("coordinates", [0, 0])
                state = p.get("state") or p.get("county") or ""
                name = p.get("name", query)
                disp_name = f"{name}, {state}" if (state and state.lower() not in name.lower()) else name
                return {
                    "name": disp_name,
                    "lat": float(coords[1]),
                    "lon": float(coords[0]),
                    "country": p.get("country", ""),
                    "country_code": (p.get("countrycode") or "").upper()
                }
    except Exception:
        pass
    return None

def geocode_place(query):
    """
    Geocodes a place name, postal code, or address to {name, lat, lon, country, country_code}.
    Uses local cache -> UK postcodes.io -> Photon (OSM) -> Open-Meteo -> Nominatim.
    Caches both successful and negative (None) lookups to prevent redundant external API calls.
    """
    if not query or not isinstance(query, str):
        return None

    clean_q = query.strip()
    if not clean_q:
        return None

    norm_key = re.sub(r'[\s,]+', ' ', clean_q.lower()).strip()
    cache = _load_cache()

    with _CACHE_LOCK:
        if norm_key in cache:
            return cache[norm_key]

    # 1. Postcode check (e.g. 'CB7 4DL', 'CB7', 'SW1A 1AA')
    pc_res = geocode_uk_postcode(clean_q)
    if pc_res:
        with _CACHE_LOCK:
            cache[norm_key] = pc_res
            _save_cache()
        return pc_res

    # Try extracting main city name if query has multiple segments (e.g. "Guildford, Surrey, UK" -> "Guildford")
    parts = [p.strip() for p in clean_q.split(",") if p.strip()]
    if parts:
        part_key = parts[0].lower()
        with _CACHE_LOCK:
            if part_key in cache and cache[part_key] is not None:
                return cache[part_key]

    # 2. Photon OpenStreetMap Geocoder (Accurate, parses counties & city names)
    photon_res = geocode_photon(clean_q)
    if photon_res:
        with _CACHE_LOCK:
            cache[norm_key] = photon_res
            if parts and parts[0].lower() not in cache:
                cache[parts[0].lower()] = photon_res
            _save_cache()
        return photon_res

    # 3. Open-Meteo Geocoding API Fallback
    try:
        encoded = urllib.parse.quote(clean_q)
        api_url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded}&count=1&language=en&format=json"
        req = urllib.request.Request(api_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=2.5, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            results = data.get("results")
            if results and len(results) > 0:
                res = results[0]
                entry = {
                    "name": res.get("name"),
                    "lat": float(res.get("latitude")),
                    "lon": float(res.get("longitude")),
                    "country": res.get("country", ""),
                    "country_code": res.get("country_code", "").upper(),
                    "admin1": res.get("admin1", "")
                }
                with _CACHE_LOCK:
                    cache[norm_key] = entry
                    if parts and parts[0].lower() not in cache:
                        cache[parts[0].lower()] = entry
                    _save_cache()
                return entry
    except Exception:
        pass

    # 4. Fallback to OpenStreetMap Nominatim API
    try:
        encoded = urllib.parse.quote(clean_q)
        nom_url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json&limit=1&addressdetails=1"
        req = urllib.request.Request(nom_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=2.5, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data and len(data) > 0:
                res = data[0]
                addr = res.get("address", {})
                entry = {
                    "name": res.get("display_name", "").split(",")[0],
                    "lat": float(res.get("lat")),
                    "lon": float(res.get("lon")),
                    "country": addr.get("country", ""),
                    "country_code": addr.get("country_code", "").upper()
                }
                with _CACHE_LOCK:
                    cache[norm_key] = entry
                    _save_cache()
                return entry
    except Exception:
        pass

    # Negative caching: record failed lookup so subsequent jobs don't repeat network calls
    with _CACHE_LOCK:
        cache[norm_key] = None
        _save_cache()

    return None

# --- Workplace Mode & Location Extraction ---

def classify_job_workplace_mode(job):
    """
    Classifies a job into one or more workplace modes: 'remote', 'hybrid', 'on_site'.
    """
    title = (job.get("title") or "").lower()
    location = (job.get("location") or "").lower()
    department = (job.get("department") or "").lower()
    loc_type = (job.get("locationType") or "").lower()
    workplace_type = (job.get("workplaceType") or "").lower()
    is_remote_flag = bool(job.get("remote") or job.get("is_remote"))
    is_hybrid_flag = bool(job.get("hybrid") or job.get("is_hybrid"))

    full_text = f"{title} {location} {department} {loc_type} {workplace_type}"
    modes = set()

    # 1. Hybrid detection (check flags, keyword 'hybrid', 'flexible', or 'part-remote')
    if is_hybrid_flag or any(w in full_text for w in ["hybrid", "flexible", "part remote", "part-remote", "office/remote"]):
        modes.add("hybrid")

    # 2. Remote detection
    if is_remote_flag or any(w in full_text for w in ["remote", "wfh", "work from home", "anywhere", "telecommute"]):
        modes.add("remote")

    # 3. On-site detection
    if any(w in full_text for w in ["on-site", "onsite", "in-office", "in office", "office-based", "studio-based"]):
        modes.add("on_site")
    elif "hybrid" in modes and location and location.strip().lower() not in ["remote", "worldwide", "anywhere"]:
        # Hybrid roles with a physical location inherently include an on-site office component
        modes.add("on_site")
    elif location and "remote" not in location:
        # If a physical city is mentioned without being remote-only
        modes.add("on_site")

    # Default fallback: if no mode explicitly detected
    if not modes:
        if is_hybrid_flag:
            modes.add("hybrid")
        elif is_remote_flag:
            modes.add("remote")
        else:
            modes.add("on_site")

    return modes

def extract_candidate_locations(job):
    """
    Extracts physical place name tokens from job metadata for distance geocoding.
    """
    candidates = []
    
    # 1. Direct fields
    city = (job.get("city") or "").strip()
    state = (job.get("state") or "").strip()
    country = (job.get("country") or "").strip()
    if city:
        candidates.append(f"{city}, {country}" if country else city)
        candidates.append(city)

    # 2. Location string parsing
    raw_loc = (job.get("location") or "").strip()
    if raw_loc:
        # Remove tags like 'Remote • ', 'Hybrid • ', brackets, etc.
        cleaned = re.sub(r'\b(remote|hybrid|onsite|on-site|full-time|permanent|contract)\b', '', raw_loc, flags=re.IGNORECASE)
        cleaned = cleaned.replace("•", ",").replace("|", ",").replace("/", ",")
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        for p in parts:
            if len(p) >= 2 and not p.isdigit():
                candidates.append(p)
        if len(parts) >= 2:
            candidates.append(f"{parts[0]}, {parts[-1]}")

    # Remove duplicates while preserving order
    unique_candidates = []
    for c in candidates:
        if c and c not in unique_candidates:
            unique_candidates.append(c)

    return unique_candidates

def is_country_or_location_in_region(loc_text, region_name):
    """
    Checks if a location string or country belongs to a target region (e.g. 'Europe', 'UK', 'North America').
    """
    if not region_name or region_name.lower() in ["all", "any", "worldwide", "global"]:
        return True

    text_lower = loc_text.lower()
    reg_lower = region_name.lower().strip()

    if reg_lower in ["europe", "eu", "emea"]:
        return any(c in text_lower for c in EUROPE_COUNTRY_NAMES)
    
    if reg_lower in ["uk", "united kingdom", "gb", "great britain"]:
        return any(c in text_lower for c in ["uk", "united kingdom", "great britain", "england", "scotland", "wales", "london", "cambridge", "edinburgh", "guildford", "manchester", "bristol", "leamington", "sheffield", "leeds", "newcastle", "oxford"])

    if reg_lower in ["north america", "na", "us/ca", "usa"]:
        return any(c in text_lower for c in NORTH_AMERICA_NAMES)

    return reg_lower in text_lower

# --- Multi-Rule Location Evaluator ---

def evaluate_location_rules(job, location_rules=None, legacy_location_filter=None, legacy_remote_only=False):
    """
    Evaluates whether a job satisfies the user's location rules.

    Returns:
        (is_match: bool, match_details: dict)
        match_details contains info for UI display:
        {
            "matched_rule": str,
            "mode": str,
            "distance_miles": float or None,
            "display_badge": str
        }
    """
    job_modes = classify_job_workplace_mode(job)
    job_loc_str = (job.get("location") or job.get("city") or "").strip()
    job_title = (job.get("title") or "").strip()
    full_loc_context = f"{job_loc_str} {job_title} {job.get('country', '')} {job.get('state', '')}".lower()

    # If modern location_rules are provided and not empty
    active_rules = [r for r in (location_rules or []) if r.get("enabled", True)]
    
    if active_rules:
        # Sort rules so specific location/distance and hybrid rules evaluate before broad remote rules
        def _rule_priority(r):
            m = (r.get("mode") or "").lower()
            has_target = bool((r.get("target") or "").strip())
            has_dist = r.get("max_distance_miles") is not None
            # Highest priority: Hybrid with target/distance, then On-site with target/dist, then other targeted, then broad
            if m == "hybrid" and (has_target or has_dist):
                return 0
            if has_dist:
                return 1
            if has_target and m != "remote":
                return 2
            if m == "hybrid":
                return 3
            if has_target:
                return 4
            return 5

        sorted_rules = sorted(active_rules, key=_rule_priority)

        for rule in sorted_rules:
            rule_mode = (rule.get("mode") or "any").lower().replace("-", "_")
            rule_target = (rule.get("target") or "").strip()
            max_dist = rule.get("max_distance_miles")
            try:
                max_dist = float(max_dist) if max_dist is not None and str(max_dist).strip() != "" else None
            except (ValueError, TypeError):
                max_dist = None

            # Mode check
            mode_matches = False
            if rule_mode == "any":
                mode_matches = True
            elif rule_mode == "remote" and "remote" in job_modes:
                # If role is exclusively hybrid/office and doesn't offer full remote, don't match broad remote
                if "hybrid" in job_modes and not any(w in full_loc_context for w in ["remote", "wfh", "work from home", "anywhere"]):
                    mode_matches = False
                else:
                    mode_matches = True
            elif rule_mode == "hybrid" and ("hybrid" in job_modes or "on_site" in job_modes):
                # Many hybrid roles are tagged as hybrid or on-site with flexible office
                mode_matches = "hybrid" in job_modes or ("remote" not in full_loc_context and "on_site" in job_modes)
            elif rule_mode in ["on_site", "onsite"] and "on_site" in job_modes:
                mode_matches = True

            if not mode_matches:
                continue

            # If rule is pure Remote (optionally constrained by region)
            if rule_mode == "remote":
                if not rule_target or is_country_or_location_in_region(full_loc_context, rule_target):
                    is_hyb = "hybrid" in job_modes
                    prefix = "Hybrid / Remote" if is_hyb else "Remote"
                    badge = f"{prefix} ({rule_target})" if rule_target else prefix
                    return True, {
                        "matched_rule": rule.get("description") or f"{prefix} ({rule_target or 'Anywhere'})",
                        "mode": "hybrid" if is_hyb else "remote",
                        "distance_miles": None,
                        "display_badge": badge
                    }
                continue

            # If rule specifies a target location and/or max distance
            if rule_target:
                # 1. Geocode target place
                target_geo = geocode_place(rule_target)

                # If distance radius is specified and we have target coordinates
                if max_dist is not None and target_geo and target_geo.get("lat") and target_geo.get("lon"):
                    candidates = extract_candidate_locations(job)
                    matched_dist = None

                    # If target is mentioned in text directly, distance is 0
                    if rule_target.lower() in full_loc_context:
                        matched_dist = 0.0
                    else:
                        for cand in candidates:
                            cand_geo = geocode_place(cand)
                            if cand_geo and cand_geo.get("lat") and cand_geo.get("lon"):
                                dist = haversine_distance(
                                    target_geo["lat"], target_geo["lon"],
                                    cand_geo["lat"], cand_geo["lon"],
                                    unit="miles"
                                )
                                if dist is not None:
                                    if matched_dist is None or dist < matched_dist:
                                        matched_dist = dist

                    if matched_dist is not None and matched_dist <= max_dist:
                        mode_label = "Hybrid" if "hybrid" in job_modes else ("On-site" if "on_site" in job_modes else "Office")
                        dist_rounded = round(matched_dist)
                        badge = f"{mode_label} • {dist_rounded} mi from {target_geo['name']}"
                        return True, {
                            "matched_rule": rule.get("description") or f"{mode_label} within {max_dist} mi of {rule_target}",
                            "mode": "hybrid" if "hybrid" in job_modes else rule_mode,
                            "distance_miles": dist_rounded,
                            "display_badge": badge
                        }
                else:
                    # Text/keyword matching on target (e.g. "London", "Cambridge")
                    if rule_target.lower() in full_loc_context or is_country_or_location_in_region(full_loc_context, rule_target):
                        mode_label = "Hybrid" if "hybrid" in job_modes else "On-site"
                        return True, {
                            "matched_rule": rule.get("description") or f"{mode_label} in {rule_target}",
                            "mode": "hybrid" if "hybrid" in job_modes else rule_mode,
                            "distance_miles": None,
                            "display_badge": f"{mode_label} • {rule_target}"
                        }
            else:
                # Rule has no target location, matches purely on workplace mode
                mode_label = "Hybrid" if "hybrid" in job_modes else ("Remote" if "remote" in job_modes else "On-site")
                return True, {
                    "matched_rule": rule.get("description") or mode_label,
                    "mode": "hybrid" if "hybrid" in job_modes else rule_mode,
                    "distance_miles": None,
                    "display_badge": mode_label
                }

        # None of the active location rules matched
        return False, {}

    # --- Legacy Fallback Logic ---
    if legacy_remote_only:
        if "remote" not in job_modes:
            return False, {}

    legacy_filter = [loc.lower().strip() for loc in (legacy_location_filter or []) if loc.strip()]
    if legacy_filter:
        if not any(loc in full_loc_context for loc in legacy_filter):
            return False, {}

    mode_label = "Hybrid" if "hybrid" in job_modes else ("Remote" if "remote" in job_modes else "On-site")
    mode_key = "hybrid" if "hybrid" in job_modes else ("remote" if "remote" in job_modes else "on_site")
    return True, {
        "matched_rule": "Default",
        "mode": mode_key,
        "distance_miles": None,
        "display_badge": mode_label if not job_loc_str else (f"{mode_label} • {job_loc_str}" if mode_label != "On-site" else job_loc_str)
    }
