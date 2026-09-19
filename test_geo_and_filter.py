"""
Comprehensive test script for Location Rules, Distance Calculation, and Workplace Filtering
"""

import os
import sys
import json
import geo_utils
import web_app
import career_monitor
import job_monitor

def run_tests():
    print("=== 1. Haversine Distance Test ===")
    d1 = geo_utils.haversine_distance(51.5074, -0.1278, 51.2362, -0.5704) # London to Guildford
    d2 = geo_utils.haversine_distance(51.5074, -0.1278, 52.2053, 0.1218) # London to Cambridge
    print(f"London -> Guildford: {d1:.2f} miles (Expected ~26.75)")
    print(f"London -> Cambridge: {d2:.2f} miles (Expected ~49.3)")
    assert 25 < d1 < 28, "Guildford distance incorrect"
    assert 45 < d2 < 55, "Cambridge distance incorrect"

    print("\n=== 2. Geocoding Resolution Test ===")
    g_lon = geo_utils.geocode_place("London")
    g_cam = geo_utils.geocode_place("Cambridge")
    print(f"London: {g_lon}")
    print(f"Cambridge: {g_cam}")
    assert g_lon and g_lon["country_code"] == "GB"
    assert g_cam and g_cam["country_code"] == "GB"

    print("\n=== 3. Workplace Mode Classification Test ===")
    m1 = geo_utils.classify_job_workplace_mode({"title": "Tech Artist", "location": "Hybrid - London", "remote": False})
    m2 = geo_utils.classify_job_workplace_mode({"title": "Tech Artist (Remote)", "location": "Anywhere", "remote": True})
    m3 = geo_utils.classify_job_workplace_mode({"title": "Pipeline TD", "location": "Cambridge, UK", "remote": False})
    print(f"Hybrid job modes: {m1}")
    print(f"Remote job modes: {m2}")
    print(f"On-site job modes: {m3}")
    assert "hybrid" in m1
    assert "remote" in m2
    assert "on_site" in m3

    print("\n=== 4. Multi-Rule Location Filter Test ===")
    config = {
        "keywords": ["tech artist", "technical artist", "shader"],
        "exclude_keywords": ["unpaid"],
        "exclude_companies": ["BadStudio"],
        "location_rules": [
            {
                "id": "r1",
                "enabled": True,
                "mode": "remote",
                "target": "Europe",
                "description": "Remote in Europe"
            },
            {
                "id": "r2",
                "enabled": True,
                "mode": "hybrid",
                "target": "London",
                "max_distance_miles": 30,
                "description": "Hybrid within 30 miles of London"
            },
            {
                "id": "r3",
                "enabled": True,
                "mode": "on_site",
                "target": "Cambridge",
                "max_distance_miles": 20,
                "description": "On-site within 20 miles of Cambridge"
            }
        ]
    }

    # Job A: Hybrid in Guildford (27 miles from London) -> MATCH via Rule 2
    job_a = {"title": "Senior Tech Artist", "company": "SuperGames", "location": "Guildford, UK", "remote": False}
    match_a, kws_a, loc_a = web_app.filter_job(job_a, config)
    print("Job A (Guildford Hybrid/Onsite):", match_a, loc_a.get("display_badge"))
    assert match_a == True

    # Job B: On-site in Cambridge -> MATCH via Rule 3
    job_b = {"title": "Shader Programmer", "company": "CamStudio", "location": "Cambridge, UK", "remote": False}
    match_b, kws_b, loc_b = web_app.filter_job(job_b, config)
    print("Job B (Cambridge On-site):", match_b, loc_b.get("display_badge"))
    assert match_b == True

    # Job C: Remote in Germany (Europe) -> MATCH via Rule 1
    job_c = {"title": "Lead Technical Artist", "company": "BerlinGames", "location": "Remote • Germany", "remote": True}
    match_c, kws_c, loc_c = web_app.filter_job(job_c, config)
    print("Job C (Remote Germany):", match_c, loc_c.get("display_badge"))
    assert match_c == True

    # Job D: Remote in United States -> FAIL (Outside Europe rule)
    job_d = {"title": "Lead Technical Artist", "company": "USGames", "location": "Remote • Seattle, United States", "remote": True}
    match_d, _, _ = web_app.filter_job(job_d, config)
    print("Job D (Remote US):", match_d)
    assert match_d == False

    # Job E: On-site in Manchester (~160 miles from London, ~125 miles from Cambridge) -> FAIL
    job_e = {"title": "Technical Artist", "company": "ManchStudio", "location": "Manchester, UK", "remote": False}
    match_e, _, _ = web_app.filter_job(job_e, config)
    print("Job E (Manchester On-site):", match_e)
    assert match_e == False

    print("\n=== 5. Career & Job Monitor Filter Check ===")
    assert career_monitor.is_matching_job(job_a, config) == True
    assert career_monitor.is_matching_job(job_d, config) == False
    
    asgc_job_a = {"title": "Tech Artist", "companyName": "CamStudio", "country": "United Kingdom", "city": "Cambridge", "locationType": "On-site"}
    assert job_monitor.matches_filters(asgc_job_a, config) == True
    
    asgc_job_d = {"title": "Tech Artist", "companyName": "USGames", "country": "United States", "locationType": "Remote"}
    assert job_monitor.matches_filters(asgc_job_d, config) == False

    print("\n=== 6. Date Parsing & Normalization Test ===")
    d_iso, ts_iso = web_app.parse_date_to_timestamp("2026-08-28T14:30:00Z")
    d_epoch, ts_epoch = web_app.parse_date_to_timestamp(1788337723000)
    d_str, ts_str = web_app.parse_date_to_timestamp("28 Aug 2026")
    d_gji_utc, ts_gji_utc = web_app.parse_date_to_timestamp("2026-08-21 11:33:16 UTC")
    d_gji_old, ts_gji_old = web_app.parse_date_to_timestamp("2025-12-23 13:08:31 UTC")
    d_nano, ts_nano = web_app.parse_date_to_timestamp("2026-08-21T17:58:14.123456789Z")
    d_rel, ts_rel = web_app.parse_date_to_timestamp("Posted 2 days ago")

    print(f"ISO parse: {d_iso}, ts: {ts_iso}")
    print(f"Epoch ms parse: {d_epoch}, ts: {ts_epoch}")
    print(f"Human date parse: {d_str}, ts: {ts_str}")
    print(f"GJI SQL UTC parse: {d_gji_utc}, ts: {ts_gji_utc}")
    print(f"GJI 2025 UTC parse: {d_gji_old}, ts: {ts_gji_old}")
    print(f"Nanosecond ISO parse: {d_nano}, ts: {ts_nano}")
    print(f"Relative date parse: {d_rel}, ts: {ts_rel}")

    assert ts_iso > 0 and d_iso == "28 Aug 2026"
    assert ts_epoch > 0
    assert ts_str > 0 and d_str == "28 Aug 2026"
    assert ts_gji_utc > 0 and d_gji_utc == "21 Aug 2026"
    assert ts_gji_old > 0 and d_gji_old == "23 Dec 2025"
    assert ts_nano > 0 and d_nano == "21 Aug 2026"
    assert ts_rel > 0

    # Chronological sort order verification
    jobs_sample = [
        {"title": "Job 2025", "company": "Companion Group", "date_posted": "2025-12-23 13:08:31 UTC"},
        {"title": "Job Aug 2026", "company": "11bitstudios", "date_posted": "2026-08-21 11:33:16 UTC"},
        {"title": "Job 18 Sep", "company": "ASGC Studio", "date_posted": "18 Sep 2026"},
        {"title": "Job 11 Sep", "company": "Framestore", "date_posted": "11 Sep 2026"},
    ]
    for j in jobs_sample:
        d, ts = web_app.parse_date_to_timestamp(j["date_posted"])
        j["date_posted"] = d
        j["date_posted_ts"] = ts
    jobs_sample.sort(key=lambda x: -x["date_posted_ts"])
    ordered_dates = [j["date_posted"] for j in jobs_sample]
    print(f"Chronologically sorted order: {ordered_dates}")
    assert ordered_dates == ["18 Sep 2026", "11 Sep 2026", "21 Aug 2026", "23 Dec 2025"]

    print("\n=== 7. Hybrid Workplace Recognition & Priority Test ===")
    # Hybrid role in London with hybrid rule should display Hybrid badge and mode
    job_h = {
        "title": "Technical Artist (Hybrid)",
        "company": "Rocksteady",
        "location": "London, UK",
        "hybrid": True,
        "remote": False
    }
    match_h, _, loc_h = web_app.filter_job(job_h, config)
    print("Job H (Hybrid London):", match_h, loc_h)
    assert match_h == True
    assert loc_h.get("mode") == "hybrid"
    assert "Hybrid" in loc_h.get("display_badge")

    # Role with 'UK / Hybrid / Remote' evaluated with hybrid target should match hybrid
    job_hr = {
        "title": "Lead Technical Artist",
        "company": "Frontier",
        "location": "Cambridge, UK / Hybrid / Remote",
        "hybrid": True,
        "remote": True
    }
    match_hr, _, loc_hr = web_app.filter_job(job_hr, config)
    print("Job HR (Cambridge Hybrid/Remote):", match_hr, loc_hr)
    assert match_hr == True
    assert loc_hr.get("mode") == "hybrid"
    assert "Hybrid" in loc_hr.get("display_badge")

    # Fallback when no location rules configured:
    _, fb_hybrid = geo_utils.evaluate_location_rules({"title": "Tech Artist (Hybrid)", "location": "London"})
    print("Fallback Hybrid Badge:", fb_hybrid)
    assert fb_hybrid.get("mode") == "hybrid"
    assert "Hybrid" in fb_hybrid.get("display_badge")

    print("\n=== 8. Games Jobs Index Harvester & Schema Test ===")
    import gamesjobsindex_monitor
    gji_jobs = gamesjobsindex_monitor.fetch_gamesjobsindex_jobs()
    print(f"Fetched {len(gji_jobs):,} jobs from Games Jobs Index")
    assert len(gji_jobs) > 1000
    sample = gji_jobs[0]
    assert sample.get("source") == "Games Jobs Index"
    assert sample.get("id").startswith("gji_")
    assert sample.get("url")
    assert sample.get("title")
    assert sample.get("company")
    
    # Filter test with sample matching role
    mock_gji_job = {
        "id": "gji_test_123",
        "title": "Principal Technical Artist",
        "company": "Supercell",
        "location": "London, United Kingdom, GB",
        "country": "GB",
        "hybrid": True,
        "remote": False,
        "url": "https://supercell.com/careers/123",
        "source": "Games Jobs Index"
    }
    match_gji, kws, loc_info = web_app.filter_job(mock_gji_job, config)
    print("Mock GJI Match:", match_gji, "Keywords:", kws, "Loc:", loc_info)
    assert match_gji == True
    assert "technical artist" in kws

    print("\n[ALL TESTS PASSED SUCCESSFULLY!]")

if __name__ == "__main__":
    run_tests()
