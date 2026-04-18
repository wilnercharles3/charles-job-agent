# app.py - Streamlit cloud UI for Job Match Agent.
# UX Flow:
#   1. User fills out profile form (name, email, resume, preferences)
#   2. On first submit: profile saved + welcome email sent
#   3. On subsequent submits: profile updated (no welcome email)
#   4. After save: Instant Job Scan button appears
#   5. On scan: fetches jobs, grades with AI, displays AND emails results
#   6. Jobs already sent within the last 14 days are excluded
# DO NOT remove the profile form or the Supabase save logic.

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date

import streamlit as st
import PyPDF2

import db
import grader
from jobs import fetch_all_jobs, pre_filter
from grader import grade_all_jobs
from welcome_email import send_welcome_email, send_profile_update_email
from db import is_new_user, mark_jobs_sent, filter_unsent_jobs

APP_URL = "https://charles-job-agent-9cpadgvzhra8g38wsrjecd.streamlit.app/"


def extract_text_from_pdf(uploaded_file):
    try:
        reader = PyPDF2.PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            c = page.extract_text()
            if c:
                text += c
        return text.strip()
    except Exception as e:
        st.error("PDF Extraction Error: " + str(e))
        return None


def clean_description(desc, max_len=300):
    """Return a cleaned snippet of the job description."""
    if not desc:
        return "No description available."
    text = desc.replace("\n", " ").replace("\r", " ").strip()
    text = " ".join(text.split())
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


# -- Instant scan email builder --------------------------------------------


def _build_job_card_html(job):
    """Build one HTML card for a graded job."""
    g = job.get("grade", {})
    rating = g.get("rating", 0)
    label = g.get("label", "PROFESSIONAL")
    reason = g.get("reason", "")
    star_full = "\u2605"
    star_empty = "\u2606"
    stars = star_full * rating + star_empty * (5 - rating)
    url = job.get("url", "#")
    title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "")
    source = job.get("source", "")
    color = "#1a8c4e" if label == "STRATEGIC" else "#1565c0"
    h = '<div style="border:1px solid #e0e0e0;border-radius:8px;padding:18px 22px;margin-bottom:18px;">\n'
    h += '<div style="font-size:18px;font-weight:700;color:#111;">' + title + '</div>\n'
    h += '<div style="font-size:14px;color:#555;margin:4px 0;">'
    h += company + " &bull; " + location + " &bull; " + source + '</div>\n'
    h += '<div style="font-size:20px;color:#f4a800;letter-spacing:2px;margin:8px 0;">'
    h += stars + ' <span style="font-size:13px;color:' + color
    h += ';font-weight:700;margin-left:8px;">[' + label + ']</span></div>\n'
    h += '<div style="font-size:13px;color:#444;font-style:italic;margin-bottom:12px;">'
    h += reason + '</div>\n'
    h += '<a href="' + url + '" style="background:#1565c0;color:#fff;padding:9px 20px;'
    h += 'border-radius:5px;text-decoration:none;font-size:14px;">Apply Now &rarr;</a>\n'
    h += '</div>\n'
    return h


def _build_scan_email(user_data, approved_jobs):
    """Build HTML email body for instant scan results."""
    name = user_data.get("full_name", "there").split()[0]
    today = date.today().strftime("%B %d, %Y")
    cards = ""
    for job in approved_jobs:
        cards += _build_job_card_html(job)
    html = '<!DOCTYPE html><html><body style="background:#f9f9f9;padding:30px 0;'
    html += 'font-family:Arial,sans-serif;">\n'
    html += '<div style="max-width:620px;margin:auto;background:#fff;border-radius:10px;'
    html += 'padding:30px 36px;">\n'
    html += '<h1 style="font-size:22px;color:#111;">Job Match Agent</h1>\n'
    html += '<p style="color:#666;font-size:14px;">Instant Scan Results - ' + today + '</p>\n'
    html += '<hr style="border:none;border-top:1px solid #eee;margin:20px 0;">\n'
    html += '<p style="font-size:15px;color:#333;">Hi ' + name + ',</p>\n'
    html += '<p style="font-size:14px;color:#555;">Here are the top matches from your '
    html += 'instant scan. Only roles scoring 3+ stars made the cut.</p>\n'
    html += cards
    html += '<div style="text-align:center;margin:24px 0;">'
    html += '<a href="' + APP_URL + '" style="display:inline-block;background:#1a73e8;'
    html += 'color:#fff;text-decoration:none;padding:12px 28px;border-radius:6px;'
    html += 'font-size:15px;font-weight:bold;">Open Job Match Agent</a></div>\n'
    html += '<hr style="border:none;border-top:1px solid #eee;margin:24px 0;">\n'
    html += '<p style="font-size:12px;color:#aaa;text-align:center;">Job Match Agent<br>'
    html += '<a href="' + APP_URL + '" style="color:#1a73e8;">' + APP_URL + '</a></p>\n'
    html += '</div></body></html>'
    return html


def _send_scan_email(to_email, approved_jobs, user_data):
    """Email the instant scan results to the user."""
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass or not to_email:
        return False
    html = _build_scan_email(user_data, approved_jobs)
    today = date.today().strftime("%B %d, %Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Job Matches - " + today
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to_email, msg.as_string())
        return True
    except Exception as e:
        print("[app] Scan email error: " + str(e))
        return False


# -- Page Config ------------------------------------------------------------
st.set_page_config(page_title="Job Match Agent", page_icon="briefcase", layout="centered")
st.title("Job Match Agent")
st.caption("Fill out your profile, save it, and then scan for matching jobs instantly.")

with st.form("profile_form"):
    st.subheader("Your Info")
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Full name")
    with col2:
        email = st.text_input("Email address")

    st.markdown("**Resume** - Upload a file OR paste your resume text below:")
    resume_file = st.file_uploader("Upload your resume (PDF or TXT)", type=["pdf", "txt"])
    resume_paste = st.text_area("Or paste your resume here",
                                placeholder="Paste your resume text here...", height=150)

    st.subheader("What You're Looking For")
    titles = st.text_input("Job title(s) you're targeting",
                           placeholder="e.g. Python Developer, Software Engineer")
    location = st.text_input("Preferred location(s)",
                             placeholder="e.g. Remote, New York")
    salary = st.number_input("Minimum base salary (annual)", min_value=0, value=0, step=5000)
    job_type = st.selectbox("Job type", ["Remote", "On-site", "Hybrid"])
    looking_for = st.text_area("Tell us what you're looking for",
                               placeholder="Describe your ideal role...")
    dealbreakers = st.text_area("Dealbreakers (optional)",
                                placeholder="e.g. No commission-only, no night shifts")
    submitted = st.form_submit_button("Save My Profile", type="primary",
                                      use_container_width=True)

if submitted:
    if not name or not email:
        st.warning("Please provide at least your name and email.")
    else:
        try:
            # Check if this is a brand-new user BEFORE saving
            first_time = is_new_user(email)

            resume_text = ""
            resume_summary = "No resume provided"

            # Try uploaded file first, then pasted text
            if resume_file:
                if resume_file.type == "application/pdf":
                    resume_text = extract_text_from_pdf(resume_file)
                else:
                    resume_text = str(resume_file.read(), "utf-8")
            elif resume_paste and resume_paste.strip():
                resume_text = resume_paste.strip()

            if resume_text:
                with st.spinner("Summarizing your resume with AI..."):
                    try:
                        resume_summary = grader.summarize_resume(resume_text)
                        if not resume_summary:
                            resume_summary = "Summary generation returned empty."
                    except Exception as ai_err:
                        resume_summary = "Summary generation failed."
                        st.warning("AI summary failed, profile still saved. Error: "
                                   + str(ai_err))

            user_data = {
                "full_name": name,
                "email": email,
                "target_titles": titles,
                "preferred_locations": location,
                "min_salary": salary,
                "job_type": job_type,
                "looking_for": looking_for,
                "dealbreakers": dealbreakers,
                "resume_summary": resume_summary,
                "resume_text": resume_text,
            }
            if not db.save_profile(user_data):
                st.error(
                    "Profile could not be saved to the database. "
                    "Check Streamlit secrets (SUPABASE_URL, SUPABASE_KEY) and "
                    "that the 'profiles' table exists with the expected columns."
                )
                st.stop()
            st.session_state["profile_saved"] = True
            st.session_state["user_data"] = user_data

            if first_time:
                st.success("Profile saved! Welcome aboard.")
                st.balloons()
                try:
                    send_welcome_email(user_data)
                    st.info("Welcome email sent! Check your inbox for tips.")
                except Exception:
                    pass
            else:
                st.success("Profile updated! You can scan for jobs below.")
                try:
                    send_profile_update_email(user_data)
                except Exception:
                    pass  # Non-fatal — profile was saved successfully

        except Exception as e:
            st.error("Error saving profile: " + str(e))
            st.info("Check your Supabase secrets (SUPABASE_URL, SUPABASE_KEY).")

# -- Instant Job Scan -------------------------------------------------------
if st.session_state.get("profile_saved"):
    st.divider()
    st.subheader("Instant Job Scan")
    st.write("Fetch and grade job listings based on your saved profile.")

    if st.button("Scan for Jobs Now", type="primary", use_container_width=True):
        ud = st.session_state["user_data"]
        user_email = ud.get("email", "")
        title_list = [t.strip() for t in ud.get("target_titles", "").split(",")
                      if t.strip()]
        loc_list = [l.strip() for l in ud.get("preferred_locations", "").split(",")
                    if l.strip()]

        if not title_list:
            st.warning("No job titles found. Please update your profile above.")
        else:
            with st.spinner("Fetching jobs from 5 job boards... "
                            "(this may take 15-30 seconds)"):
                try:
                    raw_jobs = fetch_all_jobs(title_list, loc_list)
                except Exception as e:
                    st.error("Error fetching jobs: " + str(e))
                    raw_jobs = []

            if raw_jobs:
                st.write("Fetched " + str(len(raw_jobs)) + " raw jobs. Filtering...")
                jobs = pre_filter(raw_jobs, title_list)[:25]
                # Remove jobs already sent in the last 14 days
                jobs = filter_unsent_jobs(user_email, jobs)
            else:
                jobs = []

            if not jobs:
                st.warning("No new jobs found. Try broader titles or check back "
                           "tomorrow for fresh listings.")
            else:
                st.write("Found " + str(len(jobs)) + " new jobs. Grading with AI...")
                profile_for_grader = {
                    "full_name": ud.get("full_name", ""),
                    "target_titles": ud.get("target_titles", ""),
                    "preferred_locations": ud.get("preferred_locations", ""),
                    "min_salary": ud.get("min_salary", 0),
                    "looking_for": ud.get("looking_for", ""),
                    "dealbreakers": ud.get("dealbreakers", ""),
                    "resume_summary": ud.get("resume_summary", ""),
                }
                progress = st.progress(0, text="Grading jobs...")

                def on_progress(current, total):
                    progress.progress(current / total,
                                      text="Graded " + str(current) + "/" + str(total) + " jobs...")

                try:
                    approved, graveyard, quota_exhausted = grade_all_jobs(
                        jobs, profile_for_grader, on_progress=on_progress)
                except Exception as e:
                    st.error("Grading error: " + str(e))
                    approved, graveyard, quota_exhausted = [], jobs, False
                progress.empty()

                if quota_exhausted:
                    st.warning(
                        "Our AI grader is temporarily rate-limited "
                        "(Gemini free-tier quota exhausted). "
                        "Try again in a few minutes."
                    )

                if approved:
                    # Mark these jobs as sent + email results
                    try:
                        mark_jobs_sent(user_email, approved)
                    except Exception:
                        pass
                    try:
                        if _send_scan_email(user_email, approved, ud):
                            st.info("Results emailed to " + user_email + " as well!")
                        else:
                            st.info("Could not email results (check Gmail secrets).")
                    except Exception:
                        pass

                    st.subheader("Top Matches (" + str(len(approved)) + ")")
                    for job in approved:
                        g = job.get("grade", {})
                        label = g.get("label", "N/A")
                        rating = g.get("rating", 0)
                        reason = g.get("reason", "")
                        trap = g.get("commission_trap", False)
                        emoji = "\u2B50" if label == "STRATEGIC" else "\u2705"
                        title_text = job.get("title", "Untitled")
                        company_text = job.get("company", "Unknown")
                        with st.expander(
                            emoji + " " + title_text + " at " + company_text
                            + " \u2014 " + str(rating) + "/5 " + label
                        ):
                            col_a, col_b = st.columns([3, 1])
                            with col_a:
                                st.markdown("**Company:** " + company_text)
                                st.markdown("**Location:** " + job.get("location", "N/A"))
                                st.markdown("**Source:** " + job.get("source", "Unknown"))
                            with col_b:
                                if job.get("url"):
                                    st.markdown("[\u27A1 Apply / View Job]("
                                                + job.get("url") + ")")
                            st.divider()
                            st.markdown("**AI Assessment:** " + reason)
                            if trap:
                                st.warning("\u26A0 Commission trap detected - "
                                           "base pay may be below 50% of total comp.")
                            desc_snippet = clean_description(
                                job.get("description", ""))
                            if (desc_snippet
                                    and desc_snippet != "No description available."):
                                st.caption("**Preview:** " + desc_snippet)
                            if job.get("url"):
                                st.markdown(
                                    "[Open full listing on "
                                    + job.get("source", "source")
                                    + " \u2197](" + job.get("url") + ")")
                else:
                    st.info("No jobs scored 3+ stars. Try broadening your "
                            "titles or adjusting dealbreakers.")

                if graveyard:
                    with st.expander("Skipped / Low-Rated Jobs ("
                                     + str(len(graveyard)) + ")"):
                        for job in graveyard:
                            g = job.get("grade", {})
                            rating = g.get("rating", 0)
                            reason = g.get("reason", "No reason")
                            link = ""
                            if job.get("url"):
                                link = (" \u2014 [View]("
                                        + job.get("url") + ")")
                            st.markdown(
                                "- **" + job.get("title", "")
                                + "** at " + job.get("company", "")
                                + " (" + job.get("source", "")
                                + ") \u2014 " + str(rating)
                                + "/5 \u2014 " + reason + link)
