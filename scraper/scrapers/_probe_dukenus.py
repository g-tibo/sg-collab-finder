"""Probe 8: inspect a single profile to see if Bio/Research populate there."""
from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_context().new_page()
    page.goto("https://www.duke-nus.edu.sg/directory", wait_until="load", timeout=60_000)
    page.wait_for_timeout(3_000)

    # First get one staff URL from page 1
    d = page.evaluate(
        """async () => {
          const r = await fetch('/directory/GetAllPemRevamp2024/null/null/1/aToz',
            {headers:{'X-Requested-With':'XMLHttpRequest'}});
          return await r.json();
        }"""
    )
    sample = d["PemStaffInfoModels"][1]  # Adam Claridge-Chang — research faculty
    print("Sample keys:", list(sample.keys()))
    print("Full_Name:", sample["Full_Name"])
    print("Url:", sample.get("Url"))
    print("Staff_Id:", sample.get("Staff_Id"))
    print("Staff_Num:", sample.get("Staff_Num"))

    # Navigate to the profile page
    profile_url = sample["Url"]
    if not profile_url.startswith("http"):
        profile_url = "https://www.duke-nus.edu.sg/directory/detail/" + profile_url.lstrip("/")
    print(f"\nFetching: {profile_url}")
    page.goto(profile_url, wait_until="load", timeout=60_000)
    page.wait_for_timeout(2_000)

    title = page.title()
    html = page.content()
    print(f"Title: {title}")
    print(f"HTML length: {len(html)}")

    # Save and extract bio/research sections
    import re
    # Look for common sections
    for keyword in ["Biography", "Research", "Bio", "About", "Publications", "Education"]:
        matches = [m.start() for m in re.finditer(rf"\b{keyword}\b", html)]
        if matches:
            print(f"  '{keyword}' found at: {matches[:5]}")

    # Save for inspection
    with open("cache/_dukenus_profile.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("\nSaved to cache/_dukenus_profile.html")

    browser.close()
