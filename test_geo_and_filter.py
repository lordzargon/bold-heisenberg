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

    print("\n[ALL TESTS PASSED SUCCESSFULLY!]")

if __name__ == "__main__":
    run_tests()
