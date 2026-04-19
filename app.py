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
        try:
            uploaded_file.seek(0)  # rewind in case an earlier rerun read the stream
        except Exception:
            pass
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
st.caption("Upload or paste your resume to auto-fill your profile. Review, edit, then save.")


# -- Session state defaults for the form (ensures keyed widgets don't clash) --
_FORM_DEFAULTS = {
    "full_name_input": "",
    "email_input": "",
    "target_titles_input": "",
    "preferred_locations_input": "",
    "min_salary_input": 0,
    "job_type_input": "Remote",
    "looking_for_input": "",
    "dealbreakers_input": "",
}
for _k, _v in _FORM_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# -- Resume Upload + Auto-Parse (outside form so widgets trigger reruns) ----
st.subheader("Start with your resume (optional)")
st.caption("Upload or paste your resume and we'll auto-fill the form below.")

col_up, col_paste = st.columns(2)
with col_up:
    resume_file = st.file_uploader("Upload PDF or TXT", type=["pdf", "txt"],
                                   key="_resume_uploader")
with col_paste:
    resume_paste = st.text_area("Or paste text",
                                placeholder="Paste your resume text here...",
                                height=120, key="_resume_paste_area")

# Compute a stable hash of the current resume input (if any) so we only re-parse on change.
_current_hash = None
if resume_file is not None:
    _current_hash = f"file:{resume_file.name}:{resume_file.size}"
elif resume_paste and resume_paste.strip():
    _current_hash = f"paste:{hash(resume_paste.strip())}"

_new_resume = (
    _current_hash is not None
    and _current_hash != st.session_state.get("_last_resume_hash")
)

if _new_resume:
    # Extract the text fresh. Try PyPDF2 first, fall back to pdfplumber for
    # PDFs with unusual font encoding or layouts.
    _resume_text = ""
    _extract_errors = []
    _extract_method = ""
    if resume_file is not None:
        if resume_file.type == "application/pdf":
            _resume_text = extract_text_from_pdf(resume_file) or ""
            if _resume_text:
                _extract_method = "PyPDF2"
            else:
                _extract_errors.append("PyPDF2 returned empty")
                # Fallback: pdfplumber
                try:
                    import pdfplumber
                    resume_file.seek(0)
                    with pdfplumber.open(resume_file) as _pdf:
                        _pages = [p.extract_text() or "" for p in _pdf.pages]
                        _resume_text = "\n".join(_pages).strip()
                    if _resume_text:
                        _extract_method = "pdfplumber (fallback)"
                    else:
                        _extract_errors.append("pdfplumber returned empty")
                except ImportError:
                    _extract_errors.append(
                        "pdfplumber not installed — can't fall back. "
                        "Run: pip install pdfplumber"
                    )
                except Exception as _pe:
                    _extract_errors.append(f"pdfplumber failed: {type(_pe).__name__}: {_pe}")
        else:
            try:
                _resume_text = str(resume_file.getvalue(), "utf-8")
                _extract_method = "text file"
            except Exception as _e:
                _extract_errors.append("Text read failed: " + str(_e))
    else:
        _resume_text = resume_paste.strip()
        _extract_method = "pasted"

    # Surface extraction failures so the user knows their PDF is unreadable
    # (neither PyPDF2 nor pdfplumber could pull text — usually a scanned image).
    if not _resume_text and resume_file is not None:
        st.error(
            "Couldn't extract any text from this PDF. It may be a scanned "
            "image (no text layer — needs OCR) or use a non-standard font. "
            "Try re-exporting from Word/Google Docs, or paste the text manually."
        )
        for _err in _extract_errors:
            st.caption(_err)

    if _resume_text:
        with st.spinner("Analyzing your resume with AI..."):
            parsed = grader.parse_resume_to_profile(_resume_text)
            summary = grader.summarize_resume(_resume_text)

        st.session_state["resume_text_stash"] = _resume_text
        st.session_state["resume_summary_stash"] = summary or "Summary generation returned empty."

        # Pre-fill form fields. Rules:
        #   - If field is at default (empty / 0) -> fill
        #   - If field matches the last value THIS parser set -> overwrite
        #     (user hasn't edited it since our last parse)
        #   - Otherwise (user typed or edited something) -> preserve
        # Shadow keys "_parsed_{key}" remember what parser last set so we can
        # tell user-edits apart from stale pre-fills on subsequent uploads.
        # Email is intentionally skipped — user types that manually.
        _FIELD_MAP = {
            "full_name_input":          ("full_name",          ""),
            "target_titles_input":      ("target_titles",      ""),
            "preferred_locations_input":("preferred_locations",""),
            "min_salary_input":         ("min_salary",         0),
            "looking_for_input":        ("looking_for",        ""),
        }
        _filled = []
        if parsed:
            for _key, (_src, _default) in _FIELD_MAP.items():
                _new_val = parsed.get(_src)
                if not _new_val:
                    continue
                _cur = st.session_state.get(_key)
                _shadow_key = f"_parsed_{_key}"
                _last_parsed = st.session_state.get(_shadow_key)

                _is_default = (
                    _cur is None
                    or _cur == _default
                    or (isinstance(_cur, str) and not _cur.strip())
                )
                _is_stale_prefill = (
                    _last_parsed is not None and _cur == _last_parsed
                )
                if _is_default or _is_stale_prefill:
                    st.session_state[_key] = _new_val
                    st.session_state[_shadow_key] = _new_val
                    _filled.append(_src)

        if _filled:
            _names = {
                "full_name": "name",
                "target_titles": "target titles",
                "preferred_locations": "location",
                "min_salary": "salary",
                "looking_for": "what you're looking for",
            }
            _human = ", ".join(_names.get(f, f) for f in _filled)
            st.success(
                f"Pre-filled from your resume: {_human}. Review and edit below before saving."
            )
        elif parsed:
            st.info("Resume analyzed — no new fields pre-filled "
                    "(you've already typed values for everything it could suggest).")
        else:
            st.info("Couldn't auto-parse the resume (AI parser may be rate-limited). "
                    "Please fill in the form below manually.")

    st.session_state["_last_resume_hash"] = _current_hash

st.divider()


# -- Profile Form (keyed widgets auto-pre-fill from session_state) ----------
with st.form("profile_form"):
    st.subheader("Your Info")
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Full name", key="full_name_input")
    with col2:
        email = st.text_input("Email address", key="email_input",
                              help="Type this yourself — we don't auto-fill email from the resume.")

    st.subheader("What You're Looking For")
    titles = st.text_input("Job title(s) you're targeting",
                           placeholder="e.g. Python Developer, Software Engineer",
                           key="target_titles_input")
    location = st.text_input("Preferred location(s)",
                             placeholder="e.g. Remote, New York",
                             key="preferred_locations_input")
    salary = st.number_input("Minimum base salary (annual)",
                             min_value=0, step=5000,
                             key="min_salary_input")
    job_type = st.selectbox("Job type", ["Remote", "On-site", "Hybrid"],
                            key="job_type_input")
    looking_for = st.text_area("Tell us what you're looking for",
                               placeholder="Describe your ideal role...",
                               key="looking_for_input")
    dealbreakers = st.text_area("Dealbreakers (optional)",
                                placeholder="e.g. No commission-only, no night shifts",
                                key="dealbreakers_input")
    submitted = st.form_submit_button("Save My Profile", type="primary",
                                      use_container_width=True)

if submitted:
    if not name or not email:
        st.warning("Please provide at least your name and email.")
    else:
        try:
            # Check if this is a brand-new user BEFORE saving
            first_time = is_new_user(email)

            # Resume text and summary were captured above when the user uploaded
            # or pasted. No re-processing on save.
            resume_text = st.session_state.get("resume_text_stash", "")
            resume_summary = st.session_state.get(
                "resume_summary_stash", "No resume provided"
            )

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
