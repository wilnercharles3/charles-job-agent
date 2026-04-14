"""
app.py - Job Match Agent: Profile Intake + Instant Job Search

A Streamlit app where users enter their profile and can instantly
search for AI-graded job matches. Also supports daily email delivery
via autopilot.py.
"""

import io
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st
from dotenv import load_dotenv

from db import load_profile, save_profile
from grader import summarize_resume, grade_all_jobs
from jobs import fetch_all_jobs, pre_filter

load_dotenv()

# -- Page Config -------------------------------------------------------------

st.set_page_config(page_title="Job Match Agent", layout="centered")

st.markdown("""
<style>
 .stApp { max-width: 750px; margin: auto; }
 .job-card {
 border: 1px solid #e0e0e0; border-radius: 10px;
 padding: 18px 22px; margin-bottom: 16px;
 background: #fff;
 }
 .job-card h4 { margin: 0 0 4px 0; color: #111; }
 .job-meta { font-size: 13px; color: #666; margin-bottom: 6px; }
 .job-stars { font-size: 20px; color: #f4a800; letter-spacing: 2px; }
 .job-label { font-size: 12px; font-weight: 700; letter-spacing: 1px; margin-left: 8px; }
 .job-reason { font-size: 13px; color: #444; font-style: italic; margin: 8px 0; }
 .label-strategic { color: #1a8c4e; }
 .label-professional { color: #1565c0; }
 .label-skip { color: #999; }
</style>
""", unsafe_allow_html=True)


# -- Helpers -----------------------------------------------------------------

def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def extract_text(file) -> str:
    """Extract text from uploaded PDF or TXT file."""
    raw = file.read()
    name = file.name.lower() if hasattr(file, "name") else ""
    if name.endswith(".pdf"):
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            pages = [p.extract_text() or "" for p in reader.pages]
            return "\n".join(pages)
        except Exception:
            return ""
    try:
        return raw.decode("utf-8")
    except Exception:
        return raw.decode("latin-1", errors="replace")


STAR_MAP = {5: "\u2605\u2605\u2605\u2605\u2605", 4: "\u2605\u2605\u2605\u2605\u2606", 3: "\u2605\u2605\u2605\u2606\u2606", 2: "\u2605\u2605\u2606\u2606\u2606", 1: "\u2605\u2606\u2606\u2606\u2606"}


def send_job_email(to_addr: str, job: dict):
    """Send a single job card to the user via email."""
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        return False
    g = job.get("grade", {})
    subject = f"Job Match: {job.get('title', '')} at {job.get('company', '')}"
    html = f'''<div style="font-family:Arial;max-width:600px;margin:auto;padding:20px;">
    <h2 style="color:#111;">{job.get("title","")}</h2>
    <p style="color:#555;">{job.get("company","")} &bull; {job.get("location","")} &bull; {job.get("source","")}</p>
    <p style="font-size:20px;color:#f4a800;">{STAR_MAP.get(g.get("rating",0), "")}</p>
    <p style="color:#444;font-style:italic;">{g.get("reason","")}</p>
    <a href="{job.get("url","#")}" style="display:inline-block;background:#1565c0;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;">Apply Now</a>
    </div>'''
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = to_addr
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(gmail_user, gmail_pass)
            smtp.sendmail(gmail_user, to_addr, msg.as_string())
        return True
    except Exception:
        return False


# -- Load existing profile from URL param ------------------------------------

params = st.query_params
prefill_email = params.get("email", "")
existing = load_profile(prefill_email) if prefill_email else {}


# -- Header ------------------------------------------------------------------

st.title("Job Match Agent")
st.caption("Fill out your profile, save it, then search for jobs instantly.")

if existing:
    st.success("Welcome back! Your profile is loaded. Update anything and save.")


# -- Profile Form ------------------------------------------------------------

with st.form("profile_form"):
    st.subheader("Your Info")

    full_name = st.text_input("Full name", value=existing.get("full_name", ""))
    email = st.text_input("Email address", value=existing.get("email", prefill_email or ""))
    uploaded_file = st.file_uploader("Upload your resume (PDF or TXT)", type=["pdf", "txt"])

    st.divider()
    st.subheader("What You're Looking For")

    target_titles = st.text_input("Job title(s) you're targeting", value=existing.get("target_titles", ""), placeholder="e.g. Product Manager, Data Analyst")
    preferred_locations = st.text_input("Preferred location(s)", value=existing.get("preferred_locations", ""), placeholder="e.g. New York, Remote, Chicago")
    min_salary = st.number_input("Minimum base salary (annual)", min_value=0, step=5000, value=int(existing.get("min_salary", 50000)))
    job_type = st.selectbox("Job type", ["Any", "Remote", "Hybrid", "On-site"], index=["Any", "Remote", "Hybrid", "On-site"].index(existing.get("job_type", "Any")))
    looking_for = st.text_area("Tell us what you're looking for", value=existing.get("looking_for", ""), placeholder="What matters to you? Industries, skills, culture, anything...", height=100)
    dealbreakers = st.text_area("Dealbreakers (optional)", value=existing.get("dealbreakers", ""), placeholder="e.g. no commission-only, no overnight shifts...", height=70)

    submitted = st.form_submit_button("Save My Profile", use_container_width=True, type="primary")


# -- Handle Save -------------------------------------------------------------

if submitted:
    errors = []
    if not email or not is_valid_email(email.strip()):
        errors.append("Please enter a valid email address.")
    if not target_titles.strip():
        errors.append("Please enter at least one target job title.")
    if not full_name.strip():
        errors.append("Please enter your name.")
    if errors:
        for err in errors:
            st.error(err)
    else:
        resume_text = existing.get("resume_text", "")
        resume_summary = existing.get("resume_summary", "")
        if uploaded_file:
            resume_text = extract_text(uploaded_file)

        profile_data = {
            "email": email.strip().lower(),
            "full_name": full_name.strip(),
            "resume_text": resume_text,
            "resume_summary": resume_summary,
            "target_titles": target_titles.strip(),
            "preferred_locations": preferred_locations.strip(),
            "min_salary": int(min_salary),
            "job_type": job_type,
            "looking_for": looking_for.strip(),
            "dealbreakers": dealbreakers.strip(),
        }

        with st.spinner("Saving your profile..."):
            saved = save_profile(profile_data)

        if saved:
            if uploaded_file and resume_text:
                with st.spinner("Analyzing your resume..."):
                    summary = summarize_resume(resume_text)
                    if summary:
                        profile_data["resume_summary"] = summary
                        save_profile(profile_data)

            st.session_state["profile_saved"] = True
            st.session_state["profile_data"] = profile_data
            clean_email = email.strip().lower()
            st.success(f"Profile saved! Daily matches will be sent to {clean_email}.")
            st.info(f"Bookmark this link to return anytime: **?email={clean_email}**")
        else:
            st.error("Something went wrong saving your profile. Please try again.")


# -- Instant Search Button ---------------------------------------------------

profile = st.session_state.get("profile_data") or existing
if profile and profile.get("target_titles"):
    st.divider()
    if st.button("Search Jobs Now", type="primary", use_container_width=True):
        titles = [t.strip() for t in profile.get("target_titles", "").split(",") if t.strip()]
        locations = [l.strip() for l in profile.get("preferred_locations", "").split(",") if l.strip()]

        with st.spinner("Searching 5 job boards..."):
            raw_jobs = fetch_all_jobs(titles, locations)
            jobs = pre_filter(raw_jobs, titles)

        if not jobs:
            st.warning("No jobs found right now. Try broadening your titles or locations.")
        else:
            with st.spinner(f"AI is grading {len(jobs)} jobs..."):
                approved, rejected = grade_all_jobs(jobs, profile)

            if not approved:
                st.warning("No strong matches found this time. The AI graded all results below threshold.")
            else:
                st.success(f"Found {len(approved)} matches!")
                user_email = profile.get("email", "")

                for i, job in enumerate(approved):
                    g = job.get("grade", {})
                    rating = g.get("rating", 0)
                    label = g.get("label", "PROFESSIONAL")
                    reason = g.get("reason", "")
                    stars = STAR_MAP.get(rating, "")
                    label_class = f"label-{label.lower()}"
                    url = job.get("url", "#")

                    st.markdown(f'''<div class="job-card">
                        <h4>{job.get("title","")}</h4>
                        <div class="job-meta">{job.get("company","")} &bull; {job.get("location","")} &bull; {job.get("source","")}</div>
                        <div><span class="job-stars">{stars}</span><span class="job-label {label_class}">[{label}]</span></div>
                        <div class="job-reason">{reason}</div>
                    </div>''', unsafe_allow_html=True)

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.link_button("Apply Now", url, use_container_width=True)
                    with col2:
                        if st.button(f"Email to Me", key=f"email_{i}"):
                            if send_job_email(user_email, job):
                                st.toast(f"Sent to {user_email}!")
                            else:
                                st.warning("Could not send email. Check Gmail settings.")
                    with col3:
                        if st.button(f"Copy Link", key=f"copy_{i}"):
                            st.code(url, language=None)
                            st.toast("Link shown above. Copy and share!")
