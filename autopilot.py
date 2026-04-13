"""
autopilot.py - Headless daily job scanner

Runs standalone via GitHub Actions. Zero Streamlit imports.
Scans job boards, grades with AI, and emails results to each user.
Imports shared modules: db.py, jobs.py, grader.py
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

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_APP_PASSWORD"]

TODAY = date.today().strftime("%B %d, %Y")


# -- Email Building ----------------------------------------------------------

STAR_MAP = {
    5: "\u2605\u2605\u2605\u2605\u2605",
    4: "\u2605\u2605\u2605\u2605\u2606",
    3: "\u2605\u2605\u2605\u2606\u2606",
    2: "\u2605\u2605\u2606\u2606\u2606",
    1: "\u2605\u2606\u2606\u2606\u2606",
}
LABEL_COLOR = {"STRATEGIC": "#1a8c4e", "PROFESSIONAL": "#1565c0"}


def build_job_card(job: dict) -> str:
    g = job["grade"]
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
        f'  <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">\n'
        f'  <p style="font-size:12px;color:#aaa;text-align:center;">'
        f'Job Match Agent &mdash; automated daily scan by AI</p>\n'
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
    print(f"[autopilot] Starting daily scan - {TODAY}")

    profiles = load_all_profiles()
    print(f"[autopilot] {len(profiles)} user profile(s) found")

    for profile in profiles:
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
        approved, graveyard = grade_all_jobs(jobs, profile)
        print(f"[autopilot] {len(approved)} approved, {len(graveyard)} rejected for {name}")

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
