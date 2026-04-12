"""
autopilot.py — headless daily job scanner
Runs standalone via GitHub Actions. Zero Streamlit imports.
"""

import json
import os
import smtplib
import time
import re
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv
from google import genai
from supabase import create_client

load_dotenv()

# ── Configuration Constants ──────────────────────────────────────────────────
MAX_TITLES = 2
MAX_LOCATIONS = 2
FORCE_JAVASCRIPT_ACTIONS_TO_NODE24 = True

# ── Clients ───────────────────────────────────────────────────────────────────
SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_PASS     = os.environ["GMAIL_APP_PASSWORD"]
ADZUNA_APP_ID  = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
RAPIDAPI_KEY   = os.getenv("RAPIDAPI_KEY", "")
SERPAPI_KEY    = os.getenv("SERPAPI_KEY", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini   = genai.Client(api_key=GEMINI_API_KEY)

TODAY = date.today().strftime("%B %d, %Y")

# ── Helpers ───────────────────────────────────────────────────────────────────
def clean_html(raw_html):
    """Remove HTML tags for better AI processing and lower token usage."""
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', raw_html)

# ── Job Sources ───────────────────────────────────────────────────────────────

def fetch_adzuna(titles: list, locations: list) -> list:
    jobs = []
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return jobs
    for title in titles[:MAX_TITLES]:
        for loc in locations[:MAX_LOCATIONS]:
            try:
                r = requests.get(
                    "https://api.adzuna.com/v1/api/jobs/us/search/1",
                    params={
                        "app_id": ADZUNA_APP_ID,
                        "app_key": ADZUNA_APP_KEY,
                        "results_per_page": 10,
                        "what": title,
                        "where": loc,
                        "content-type": "application/json",
                    },
                    timeout=10,
                )
                if r.status_code == 200:
                    for j in r.json().get("results", []):
                        jobs.append({
                            "title": j.get("title", ""),
                            "company": j.get("company", {}).get("display_name", ""),
                            "location": j.get("location", {}).get("display_name", ""),
                            "description": clean_html(j.get("description", ""))[:800],
                            "url": j.get("redirect_url", ""),
                            "source": "Adzuna",
                        })
            except Exception as e:
                print(f"[Adzuna] Error: {e}")
    return jobs

def fetch_themuse(titles: list) -> list:
    jobs = []
    for title in titles[:MAX_TITLES]:
        try:
            r = requests.get(
                "https://www.themuse.com/api/public/jobs",
                params={"category": title, "page": 1, "descending": "true"},
                timeout=10,
            )
            if r.status_code == 200:
                for j in r.json().get("results", []):
                    loc_parts = [loc.get("name", "") for loc in j.get("locations", [])]
                    jobs.append({
                        "title": j.get("name", ""),
                        "company": j.get("company", {}).get("name", ""),
                        "location": ", ".join(loc_parts),
                        "description": clean_html(j.get("contents", ""))[:800],
                        "url": j.get("refs", {}).get("landing_page", ""),
                        "source": "The Muse",
                    })
        except Exception as e:
            print(f"[The Muse] Error: {e}")
    return jobs

# ... (fetch_remoteok, fetch_jsearch, fetch_serpapi remain largely similar but use MAX_TITLES)

def deduplicate(jobs: list) -> list:
    seen = set()
    out = []
    for j in jobs:
        key = (j["title"].lower().strip(), j["company"].lower().strip())
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out

# ── Grader (Security & Logic Updates) ─────────────────────────────────────────

def grade_job(job: dict, profile: dict) -> dict:
    # Cybersecurity Fix: Wrapping description in tags to prevent prompt injection
    prompt = f"""You are a ruthless job screener. Grade this job for {profile.get('full_name','the user')} who is targeting {profile.get('target_titles','')} in {profile.get('preferred_locations','')} with minimum base salary of {profile.get('min_salary', 0)}. Their ideal role: {profile.get('ideal_role_summary','')}

Job: {job['title']} at {job['company']}. 
Location: {job['location']}. 
<job_description>
{job['description']}
</job_description>

COMMISSION TRAP RULE: If base salary appears to be less than 50% of total comp (commission-heavy, OTE-based, draw-based), return rating 0 and flag as Commission Trap.

Return JSON only — no markdown, no explanation outside the JSON:
{{"rating": 1-5, "label": "STRATEGIC|PROFESSIONAL|SKIP", "reason": "one sentence", "commission_trap": true|false}}"""

    for attempt in range(3):
        try:
            response = gemini.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            text = response.text.strip()
            # Handle potential markdown code block wrapping
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            return json.loads(text)
        except Exception as e:
            print(f"[Gemini] Attempt {attempt+1} failed: {e}")
            time.sleep(1)
    return {"rating": 0, "label": "SKIP", "reason": "Grading failed.", "commission_trap": False}

# ... (build_job_card, build_email_html, send_email remain the same)

# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print(f"[autopilot] Starting daily scan — {TODAY}")
    result = supabase.table("profiles").select("*").execute()
    profiles = result.data or []
    print(f"[autopilot] {len(profiles)} user profile(s) found")

    for profile in profiles:
        email = profile.get("email", "")
        name  = profile.get("full_name", email)
        print(f"[autopilot] Processing: {name} <{email}>")

        titles    = [t.strip() for t in profile.get("target_titles", "").split(",") if t.strip()]
        locations = [l.strip() for l in profile.get("preferred_locations", "").split(",") if l.strip()]

        if not titles:
            print(f"[autopilot] Skipping {email} — no target titles set")
            continue

        # Gather
        raw_jobs = []
        raw_jobs += fetch_adzuna(titles, locations)
        raw_jobs += fetch_themuse(titles)
        # ... other fetchers ...
        
        jobs = deduplicate(raw_jobs)
        print(f"[autopilot] {len(jobs)} unique listings for {name}")

        # Efficiency Fix: Filter out jobs already in the 'graveyard' or 'sent' status
        # Note: This assumes you have a table or column tracking job URLs or Title/Company keys
        approved = []
        for job in jobs:
            # Check Supabase if this job (url or title/company) has been graded before
            existing = supabase.table("job_history").select("id").match({
                "title": job["title"], 
                "company": job["company"],
                "user_email": email
            }).execute()
            
            if existing.data:
                # print(f"Skipping {job['title']} — already graded.")
                continue

            grade = grade_job(job, profile)
            job["grade"] = grade
            
            # Log the result to history so we don't grade it again tomorrow
            supabase.table("job_history").insert({
                "title": job["title"],
                "company": job["company"],
                "user_email": email,
                "rating": grade.get("rating", 0),
                "label": grade.get("label", "SKIP")
            }).execute()

            rating   = grade.get("rating", 0)
            is_trap  = grade.get("commission_trap", False)
            if not is_trap and rating >= 4:
                approved.append(job)

        approved.sort(key=lambda j: j["grade"]["rating"], reverse=True)
        print(f"[autopilot] {len(approved)} approved jobs for {name}")

        if not approved:
            print(f"[autopilot] No new strong matches — skipping email for {name}")
            continue

        # Email
        html    = build_email_html(profile, approved)
        subject = f"Your Daily Job Matches — {TODAY}"
        try:
            send_email(email, subject, html)
            print(f"[autopilot] Email sent to {email}")
        except Exception as e:
            print(f"[autopilot] Email failed for {email}: {e}")

if __name__ == "__main__":
    run()
