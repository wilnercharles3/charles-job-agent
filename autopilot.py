"""
autopilot.py — headless daily job scanner
Runs standalone via GitHub Actions. Zero Streamlit imports.
"""

import json
import os
import smtplib
import time
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv
from google import genai
from supabase import create_client

load_dotenv()

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

# ─────────────────────────────────────────────────────────────────────────────
# JOB SOURCES
# ─────────────────────────────────────────────────────────────────────────────

def fetch_adzuna(titles: list, locations: list) -> list:
    jobs = []
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return jobs
    for title in titles[:2]:
        for loc in locations[:2]:
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
                            "description": j.get("description", "")[:800],
                            "url": j.get("redirect_url", ""),
                            "source": "Adzuna",
                        })
            except Exception as e:
                print(f"[Adzuna] Error: {e}")
    return jobs


def fetch_themuse(titles: list) -> list:
    jobs = []
    for title in titles[:2]:
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
                        "description": j.get("contents", "")[:800],
                        "url": j.get("refs", {}).get("landing_page", ""),
                        "source": "The Muse",
                    })
        except Exception as e:
            print(f"[The Muse] Error: {e}")
    return jobs


def fetch_remoteok(titles: list) -> list:
    jobs = []
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "job-agent/1.0"},
            timeout=10,
        )
        if r.status_code == 200:
            for j in r.json()[1:]:
                t = j.get("position", "").lower()
                if any(title.lower() in t or t in title.lower() for title in titles):
                    jobs.append({
                        "title": j.get("position", ""),
                        "company": j.get("company", ""),
                        "location": j.get("location", "Remote"),
                        "description": j.get("description", "")[:800],
                        "url": j.get("url", ""),
                        "source": "RemoteOK",
                    })
    except Exception as e:
        print(f"[RemoteOK] Error: {e}")
    return jobs


def fetch_jsearch(titles: list, locations: list) -> list:
    jobs = []
    if not RAPIDAPI_KEY:
        return jobs
    for title in titles[:2]:
        query = f"{title} in {locations[0]}" if locations else title
        try:
            r = requests.get(
                "https://jsearch.p.rapidapi.com/search",
                headers={
                    "X-RapidAPI-Key": RAPIDAPI_KEY,
                    "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
                },
                params={"query": query, "page": "1", "num_pages": "1"},
                timeout=10,
            )
            if r.status_code == 200:
                for j in r.json().get("data", []):
                    jobs.append({
                        "title": j.get("job_title", ""),
                        "company": j.get("employer_name", ""),
                        "location": f"{j.get('job_city','')}, {j.get('job_state','')}".strip(", "),
                        "description": j.get("job_description", "")[:800],
                        "url": j.get("job_apply_link", ""),
                        "source": "JSearch",
                    })
        except Exception as e:
            print(f"[JSearch] Error: {e}")
    return jobs


def fetch_serpapi_google_jobs(titles: list, locations: list) -> list:
    jobs = []
    if not SERPAPI_KEY:
        return jobs
    for title in titles[:2]:
        query = f"{title} jobs {locations[0]}" if locations else f"{title} jobs"
        try:
            r = requests.get(
                "https://serpapi.com/search.json",
                params={"engine": "google_jobs", "q": query, "api_key": SERPAPI_KEY},
                timeout=10,
            )
            if r.status_code == 200:
                for j in r.json().get("jobs_results", []):
                    jobs.append({
                        "title": j.get("title", ""),
                        "company": j.get("company_name", ""),
                        "location": j.get("location", ""),
                        "description": j.get("description", "")[:800],
                        "url": j.get("related_links", [{}])[0].get("link", ""),
                        "source": "Google Jobs",
                    })
        except Exception as e:
            print(f"[SerpAPI] Error: {e}")
    return jobs


def deduplicate(jobs: list) -> list:
    seen = set()
    out = []
    for j in jobs:
        key = (j["title"].lower().strip(), j["company"].lower().strip())
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# GRADER
# ─────────────────────────────────────────────────────────────────────────────

def grade_job(job: dict, profile: dict) -> dict:
    prompt = f"""You are a ruthless job screener. Grade this job for {profile.get('full_name','the user')} who is targeting {profile.get('target_titles','')} in {profile.get('preferred_locations','')} with minimum base salary of {profile.get('min_salary', 0)}. Their ideal role: {profile.get('ideal_role_summary','')}

Job: {job['title']} at {job['company']}. Location: {job['location']}. Description: {job['description']}

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
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            print(f"[Gemini] Attempt {attempt+1} failed: {e}")
            time.sleep(1)
    return {"rating": 0, "label": "SKIP", "reason": "Grading failed.", "commission_trap": False}


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────────────────────────

STAR_MAP = {5: "★★★★★", 4: "★★★★☆", 3: "★★★☆☆", 2: "★★☆☆☆", 1: "★☆☆☆☆"}

LABEL_COLOR = {
    "STRATEGIC":    "#1a8c4e",
    "PROFESSIONAL": "#1565c0",
}


def build_job_card(job: dict) -> str:
    g = job["grade"]
    rating  = g.get("rating", 0)
    label   = g.get("label", "PROFESSIONAL")
    reason  = g.get("reason", "")
    stars   = STAR_MAP.get(rating, "")
    color   = LABEL_COLOR.get(label, "#333")
    url     = job.get("url", "#")

    return f"""
    <div style="border:1px solid #e0e0e0;border-radius:8px;padding:18px 22px;margin-bottom:18px;font-family:Arial,sans-serif;">
      <div style="font-size:18px;font-weight:700;color:#111;">{job['title']}</div>
      <div style="font-size:14px;color:#555;margin:4px 0;">{job['company']} &bull; {job['location']} &bull; {job['source']}</div>
      <div style="font-size:20px;color:#f4a800;letter-spacing:2px;margin:8px 0;">{stars}
        <span style="font-size:13px;color:{color};font-weight:700;letter-spacing:1px;margin-left:8px;">[{label}]</span>
      </div>
      <div style="font-size:13px;color:#444;font-style:italic;margin-bottom:12px;">{reason}</div>
      <a href="{url}" style="background:#1565c0;color:#fff;padding:9px 20px;border-radius:5px;text-decoration:none;font-size:13px;font-weight:600;">Apply Now →</a>
    </div>
    """


def build_email_html(profile: dict, jobs: list) -> str:
    name  = profile.get("full_name", "there")
    cards = "".join(build_job_card(j) for j in jobs)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background:#f9f9f9;padding:30px 0;font-family:Arial,sans-serif;">
  <div style="max-width:620px;margin:auto;background:#fff;border-radius:10px;padding:30px 36px;">
    <h1 style="font-size:22px;color:#111;margin-bottom:4px;">Job Match Agent</h1>
    <p style="color:#666;font-size:14px;margin-top:0;">Your daily matches for {TODAY}</p>
    <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
    <p style="font-size:15px;color:#333;">Hi {name},</p>
    <p style="font-size:14px;color:#555;">Here are your top-rated job matches from today's scan. Only roles rated 4 or 5 stars make it into your inbox.</p>
    {cards}
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
    <p style="font-size:12px;color:#aaa;text-align:center;">Job Match Agent &mdash; automated daily scan</p>
  </div>
</body>
</html>"""


def send_email(to_addr: str, subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = to_addr
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(GMAIL_USER, GMAIL_PASS)
        smtp.sendmail(GMAIL_USER, to_addr, msg.as_string())


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

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
        raw_jobs += fetch_remoteok(titles)
        raw_jobs += fetch_jsearch(titles, locations)
        raw_jobs += fetch_serpapi_google_jobs(titles, locations)
        jobs = deduplicate(raw_jobs)
        print(f"[autopilot] {len(jobs)} unique listings for {name}")

        # Grade
        approved = []
        for job in jobs:
            grade = grade_job(job, profile)
            job["grade"] = grade
            rating   = grade.get("rating", 0)
            is_trap  = grade.get("commission_trap", False)
            if not is_trap and rating >= 4:
                approved.append(job)

        approved.sort(key=lambda j: j["grade"]["rating"], reverse=True)
        print(f"[autopilot] {len(approved)} approved jobs for {name}")

        if not approved:
            print(f"[autopilot] No strong matches — skipping email for {name}")
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
