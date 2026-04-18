"""
autopilot.py - Headless daily job scanner

Runs standalone via GitHub Actions.  Zero Streamlit imports.
Scans job boards, grades with AI, and emails results to each user.
Imports shared modules: db.py, jobs.py, grader.py

Field mapping note:
  app.py saves: name, email, target_titles, location_pref, min_salary,
                job_type, looking_for, dealbreakers, resume_summary
  autopilot/grader expects: full_name, target_titles, preferred_locations, etc.
  This module normalises both conventions so the pipeline works regardless.
"""

import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
from db import load_all_profiles, filter_unsent_jobs, mark_jobs_sent
from jobs import fetch_all_jobs, pre_filter
from grader import grade_all_jobs

load_dotenv()

# -- Email credentials -------------------------------------------------------
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")

TODAY = date.today().strftime("%B %d, %Y")

APP_URL = "https://charles-job-agent-9cpadgvzhra8g38wsrjecd.streamlit.app/"


# -- Normalise profile fields ------------------------------------------------
def normalise_profile(raw: dict) -> dict:
    """Map app.py field names to the ones autopilot/grader expect."""
    return {
        "full_name": raw.get("full_name") or raw.get("name", ""),
        "email": raw.get("email", ""),
        "target_titles": raw.get("target_titles", ""),
        "preferred_locations": raw.get("preferred_locations") or raw.get("location_pref", ""),
        "min_salary": raw.get("min_salary", 0),
        "job_type": raw.get("job_type", "Remote"),
        "looking_for": raw.get("looking_for", ""),
        "dealbreakers": raw.get("dealbreakers", ""),
        "resume_summary": raw.get("resume_summary", ""),
    }


# -- Email Building ----------------------------------------------------------
STAR_MAP = {
    5: "★★★★★",
    4: "★★★★☆",
    3: "★★★☆☆",
    2: "★★☆☆☆",
    1: "★☆☆☆☆",
}

LABEL_COLOR = {"STRATEGIC": "#1a8c4e", "PROFESSIONAL": "#1565c0"}


def build_job_card(job: dict) -> str:
    g = job.get("grade", {})
    rating = g.get("rating", 0)
    label = g.get("label", "PROFESSIONAL")
    reason = g.get("reason", "")
    stars = STAR_MAP.get(rating, "")
    color = LABEL_COLOR.get(label, "#333")
    url = job.get("url", "#")
    title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "")
    source = job.get("source", "")

    return (
        f'<div style="border:1px solid #e0e0e0;border-radius:8px;'
        f'padding:18px 22px;margin-bottom:18px;font-family:Arial,sans-serif;">\n'
        f'  <div style="font-size:18px;font-weight:700;color:#111;">{title}</div>\n'
        f'  <div style="font-size:14px;color:#555;margin:4px 0;">'
        f'{company} &bull; {location} &bull; {source}</div>\n'
        f'  <div style="font-size:20px;color:#f4a800;letter-spacing:2px;margin:8px 0;">'
        f'{stars} <span style="font-size:13px;color:{color};font-weight:700;'
        f'letter-spacing:1px;margin-left:8px;">[{label}]</span></div>\n'
        f'  <div style="font-size:13px;color:#444;font-style:italic;'
        f'margin-bottom:12px;">{reason}</div>\n'
        f'  <a href="{url}" style="background:#1565c0;color:#fff;padding:9px 20px;'
        f'border-radius:5px;text-decoration:none;font-size:14px;">Apply Now &rarr;</a>\n'
        f'</div>\n'
    )


def build_email_html(profile: dict, jobs: list) -> str:
    name = profile.get("full_name", "there")
    cards = "".join(build_job_card(j) for j in jobs)

    return (
        f'<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"></head>\n'
        f'<body style="background:#f9f9f9;padding:30px 0;font-family:Arial,sans-serif;">\n'
        f'<div style="max-width:620px;margin:auto;background:#fff;border-radius:10px;padding:30px 36px;">\n'
        f'  <h1 style="font-size:22px;color:#111;margin-bottom:4px;">Job Match Agent</h1>\n'
        f'  <p style="color:#666;font-size:14px;margin-top:0;">Your daily matches for {TODAY}</p>\n'
        f'  <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">\n'
        f'  <p style="font-size:15px;color:#333;">Hi {name},</p>\n'
        f'  <p style="font-size:14px;color:#555;">Here are your top-rated job matches. '
        f'Only roles scoring 3+ stars made the cut.</p>\n'
        f'  {cards}\n'
        f'  <div style="text-align:center;margin:24px 0;">'
        f'<a href="{APP_URL}" style="display:inline-block;background:#1a73e8;color:#fff;'
        f'text-decoration:none;padding:12px 28px;border-radius:6px;font-size:15px;'
        f'font-weight:bold;">Open Job Match Agent</a></div>\n'
        f'  <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">\n'
        f'  <p style="font-size:12px;color:#aaa;text-align:center;">'
        f'Job Match Agent &mdash; automated daily scan by AI<br>'
        f'<a href="{APP_URL}" style="color:#1a73e8;">{APP_URL}</a></p>\n'
        f'</div>\n</body>\n</html>'
    )


def send_email(to_addr: str, subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(GMAIL_USER, GMAIL_PASS)
        smtp.sendmail(GMAIL_USER, to_addr, msg.as_string())


# -- Main --------------------------------------------------------------------
def run():
    if not GMAIL_USER or not GMAIL_PASS:
        print("[autopilot] Gmail credentials missing - cannot send emails.")
        return

    print(f"[autopilot] Starting daily scan - {TODAY}")

    raw_profiles = load_all_profiles()
    print(f"[autopilot] {len(raw_profiles)} user profile(s) found")

    for raw in raw_profiles:
        profile = normalise_profile(raw)
        email = profile.get("email", "")
        name = profile.get("full_name", email)

        print(f"[autopilot] Processing: {name} <{email}>")

        titles = [t.strip() for t in profile.get("target_titles", "").split(",") if t.strip()]
        locations = [l.strip() for l in profile.get("preferred_locations", "").split(",") if l.strip()]

        if not titles:
            print(f"[autopilot] Skipping {email} - no target titles set")
            continue

        # Fetch jobs from all sources
        jobs = fetch_all_jobs(titles, locations)
        print(f"[autopilot] {len(jobs)} unique listings for {name}")

        # Pre-filter obvious mismatches
        jobs = pre_filter(jobs, titles)

        # Remove jobs already sent to this user
        jobs = filter_unsent_jobs(email, jobs)
        print(f"[autopilot] {len(jobs)} new jobs after dedup for {name}")

        if not jobs:
            print(f"[autopilot] No new jobs - skipping email for {name}")
            continue

        # Grade with AI
        approved, graveyard, quota_exhausted = grade_all_jobs(jobs, profile)
        print(f"[autopilot] {len(approved)} approved, {len(graveyard)} rejected for {name}")

        if quota_exhausted:
            print(f"[autopilot] Gemini quota exhausted - skipping remaining users.")
            break

        if not approved:
            print(f"[autopilot] No strong matches - skipping email for {name}")
            continue

        # Send email
        html = build_email_html(profile, approved)
        subject = f"Your Daily Job Matches - {TODAY}"

        try:
            send_email(email, subject, html)
            print(f"[autopilot] Email sent to {email}")
            mark_jobs_sent(email, approved)
        except Exception as e:
            print(f"[autopilot] Email failed for {email}: {e}")

    print("[autopilot] Daily scan complete.")


if __name__ == "__main__":
    run()
