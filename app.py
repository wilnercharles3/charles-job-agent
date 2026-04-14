# app.py - Streamlit cloud UI for Job Match Agent.
# UX Flow:
#  1. User fills out profile form (name, email, resume, preferences)
#  2. On submit: resume is summarized by AI, profile saved to Supabase
#  3. After save: welcome email sent + Instant Job Scan button appears
#  4. On scan: fetches jobs from 5 boards, grades with Gemini, displays results
# DO NOT remove the profile form or the Supabase save logic.

import streamlit as st
import PyPDF2
import io
import db
import grader
from jobs import fetch_all_jobs, pre_filter
from grader import grade_all_jobs
from welcome_email import send_welcome_email


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
        st.error(f"PDF Extraction Error: {e}")
        return None


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
    resume_paste = st.text_area("Or paste your resume here", placeholder="Paste your resume text here...", height=150)

    st.subheader("What You're Looking For")
    titles = st.text_input("Job title(s) you're targeting", placeholder="e.g. Python Developer, Software Engineer")
    location = st.text_input("Preferred location(s)", placeholder="e.g. Remote, New York")
    salary = st.number_input("Minimum base salary (annual)", min_value=0, value=0, step=5000)
    job_type = st.selectbox("Job type", ["Remote", "On-site", "Hybrid"])
    looking_for = st.text_area("Tell us what you're looking for", placeholder="Describe your ideal role...")
    dealbreakers = st.text_area("Dealbreakers (optional)", placeholder="e.g. No commission-only, no night shifts")
    submitted = st.form_submit_button("Save My Profile", type="primary", use_container_width=True)

if submitted:
    if not name or not email:
        st.warning("Please provide at least your name and email.")
    else:
        try:
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
                        st.warning(f"AI summary failed, profile still saved. Error: {ai_err}")

            user_data = {
                "name": name, "email": email, "target_titles": titles,
                "location_pref": location, "min_salary": salary, "job_type": job_type,
                "looking_for": looking_for, "dealbreakers": dealbreakers,
                "resume_summary": resume_summary,
            }
            db.save_profile(user_data)
            st.session_state["profile_saved"] = True
            st.session_state["user_data"] = user_data
            st.success("Profile saved! You can now scan for jobs below.")
            st.balloons()
            try:
                send_welcome_email()
                st.info("Welcome email sent! Check your inbox for tips on getting the best results.")
            except Exception:
                pass
        except Exception as e:
            st.error(f"Error saving profile: {e}")
            st.info("Check your Supabase secrets (SUPABASE_URL, SUPABASE_KEY).")

if st.session_state.get("profile_saved"):
    st.divider()
    st.subheader("Instant Job Scan")
    st.write("Fetch and grade job listings based on your saved profile.")
    if st.button("Scan for Jobs Now", type="primary", use_container_width=True):
        ud = st.session_state["user_data"]
        title_list = [t.strip() for t in ud.get("target_titles", "").split(",") if t.strip()]
        loc_list = [l.strip() for l in ud.get("location_pref", "").split(",") if l.strip()]
        if not title_list:
            st.warning("No job titles found. Please update your profile above.")
        else:
            with st.spinner("Fetching jobs from 5 job boards... (this may take 15-30 seconds)"):
                try:
                    raw_jobs = fetch_all_jobs(title_list, loc_list)
                except Exception as e:
                    st.error(f"Error fetching jobs: {e}")
                    raw_jobs = []
            if raw_jobs:
                st.write(f"Fetched {len(raw_jobs)} raw jobs. Filtering...")
                jobs = pre_filter(raw_jobs, title_list)[:15]
            else:
                jobs = []
            if not jobs:
                st.warning("No jobs found. Try broader titles or add more title variations separated by commas.")
            else:
                st.write(f"Found {len(jobs)} jobs. Grading with AI...")
                profile_for_grader = {
                    "full_name": ud.get("name", ""),
                    "target_titles": ud.get("target_titles", ""),
                    "preferred_locations": ud.get("location_pref", ""),
                    "min_salary": ud.get("min_salary", 0),
                    "looking_for": ud.get("looking_for", ""),
                    "dealbreakers": ud.get("dealbreakers", ""),
                    "resume_summary": ud.get("resume_summary", ""),
                }
                progress = st.progress(0, text="Grading jobs...")
                def on_progress(current, total):
                    progress.progress(current / total, text=f"Graded {current}/{total} jobs...")
                try:
                    approved, graveyard = grade_all_jobs(jobs, profile_for_grader, on_progress=on_progress)
                except Exception as e:
                    st.error(f"Grading error: {e}")
                    approved, graveyard = [], jobs
                progress.empty()
                if approved:
                    st.subheader(f"Top Matches ({len(approved)})")
                    for job in approved:
                        g = job.get("grade", {})
                        label = g.get("label", "N/A")
                        rating = g.get("rating", 0)
                        reason = g.get("reason", "")
                        trap = g.get("commission_trap", False)
                        emoji = "\u2B50" if label == "STRATEGIC" else "\u2705"
                        with st.expander(f"{emoji} {job.get('title','')} at {job.get('company','')} \u2014 {rating}/5 {label}"):
                            st.write(f"**Location:** {job.get('location','N/A')} | **Source:** {job.get('source','')}")
                            if job.get("url"):
                                st.markdown(f"[Apply Here]({job.get('url')})")
                            st.write(f"**Why:** {reason}")
                            if trap:
                                st.warning("Commission trap detected.")
                else:
                    st.info("No jobs scored 3+ stars. Try broadening your titles or adjusting dealbreakers.")
                if graveyard:
                    with st.expander(f"Skipped Jobs ({len(graveyard)})"):
                        for job in graveyard:
                            g = job.get("grade", {})
                            st.write(f"- **{job.get('title','')}** at {job.get('company','')} \u2014 {g.get('reason','No reason')}")
