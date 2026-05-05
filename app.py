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
from jobs import fetch_all_jobs, pre_filter, reject_bad_fit, rule_based_score
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


def _score_color(score: int) -> str:
    """Color band for the match-score badge."""
    if score >= 85:
        return "#1a8c4e"  # green
    if score >= 65:
        return "#1565c0"  # blue
    return "#8a6d3b"      # olive/amber


_ACTION_COLORS = {
    "Apply": "#1a8c4e",  # green
    "Maybe": "#c47900",  # amber
    "Skip":  "#777777",  # gray
}


def _action_badge_html(action: str) -> str:
    """Inline pill HTML for the recommended_action label (used in email cards)."""
    color = _ACTION_COLORS.get(action, "#555")
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        f'font-weight:700;font-size:12px;padding:3px 10px;border-radius:11px;'
        f'margin-right:8px;text-transform:uppercase;letter-spacing:0.5px;">{action}</span>'
    )


def _build_job_card_html(job):
    """Build one HTML card for a graded job (for scan/daily emails)."""
    import html as _html
    g = job.get("grade", {})
    score = int(g.get("match_score", 0) or 0)
    action = g.get("recommended_action") or "Maybe"
    rec_resume = (g.get("recommended_resume") or "").strip()
    narrative = _html.escape((g.get("narrative") or "").strip())
    role_summary = _html.escape((g.get("role_summary") or "").strip())
    reasons = [_html.escape(r.strip()) for r in (g.get("match_reasons") or []) if r and r.strip()]
    cautions = [_html.escape(c.strip()) for c in (g.get("caution_flags") or []) if c and c.strip()]
    url = job.get("url", "#")
    title = _html.escape(job.get("title", ""))
    company = _html.escape(job.get("company", ""))
    location = _html.escape(job.get("location", ""))
    source = _html.escape(job.get("source", ""))
    color = _score_color(score)

    h = (
        '<div style="border:1px solid #e0e0e0;border-radius:8px;'
        'padding:20px 22px;margin-bottom:18px;background:#fff;">\n'
    )
    # Narrative — the emotional hook, first thing the eye lands on
    if narrative:
        h += (
            '<div style="font-size:15px;color:#222;font-style:italic;'
            'line-height:1.55;margin-bottom:14px;">' + narrative + '</div>\n'
        )
    # Action badge + score badge + title header row
    h += '<div style="margin-bottom:6px;">\n'
    h += _action_badge_html(action)
    h += (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        'font-weight:700;font-size:14px;padding:4px 12px;border-radius:14px;'
        f'margin-right:10px;">{score}/100</span>\n'
    )
    if rec_resume:
        h += (
            '<span style="display:inline-block;background:#5a6c8a;color:#fff;'
            'font-size:11px;padding:3px 10px;border-radius:11px;margin-right:8px;'
            f'text-transform:uppercase;letter-spacing:0.5px;">Use: {_html.escape(rec_resume)}</span>\n'
        )
    h += (
        '<span style="font-size:17px;font-weight:700;color:#111;">'
        + title + '</span>\n'
    )
    h += '</div>\n'
    h += (
        '<div style="font-size:13px;color:#666;margin-bottom:12px;">'
        + company + ' &bull; ' + location + ' &bull; ' + source + '</div>\n'
    )
    # Role summary
    if role_summary:
        h += (
            '<div style="font-size:13px;color:#444;margin-bottom:10px;">'
            '<b>What this role is:</b> ' + role_summary + '</div>\n'
        )
    # Match reasons as bullets
    if reasons:
        h += (
            '<div style="font-size:13px;color:#333;margin-bottom:4px;">'
            '<b>Why this fits you:</b></div>\n'
        )
        h += '<ul style="margin:0 0 12px 18px;padding:0;font-size:13px;color:#333;">\n'
        for r in reasons:
            h += f'<li style="margin-bottom:4px;">{r}</li>\n'
        h += '</ul>\n'
    # Caution flags in a soft yellow box
    if cautions:
        h += (
            '<div style="background:#fff8e1;border-left:3px solid #f4a800;'
            'padding:8px 12px;margin-bottom:12px;font-size:12px;color:#5a4a00;">'
            '<b>Watch for:</b> ' + ' &middot; '.join(cautions) + '</div>\n'
        )
    # Apply button
    h += (
        f'<a href="{url}" style="display:inline-block;background:#1565c0;'
        'color:#fff;padding:9px 20px;border-radius:5px;text-decoration:none;'
        'font-size:14px;font-weight:bold;">Apply Now &rarr;</a>\n'
    )
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
    threshold = int(user_data.get("match_threshold", 50) or 50)
    html += '<p style="font-size:14px;color:#555;">Here are the top matches from your '
    html += f'instant scan. Only roles scoring {threshold}+ out of 100 made the cut.</p>\n'
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
    "preferred_industries_input": "",
    "target_companies_input": "",
    "min_salary_input": 0,
    "target_ote_input": 0,
    "match_threshold_input": 50,
    "job_type_input": "Remote",
    "looking_for_input": "",
    "dealbreakers_input": "",
}
for _k, _v in _FORM_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# -- Multi-Resume Manager (outside form so widgets trigger reruns) ----------
# Up to 3 named resumes per profile. Slot 0 is "Primary" and drives the form
# pre-fill via parse_resume_to_profile. Additional slots only get summarized
# and labeled — the grader uses them as alternative versions to recommend per job.

if "resumes" not in st.session_state:
    st.session_state["resumes"] = [{"label": "Primary", "text": "", "summary": ""}]


def _add_resume_slot():
    if len(st.session_state["resumes"]) < 3:
        st.session_state["resumes"].append({"label": "", "text": "", "summary": ""})


def _remove_resume_slot(i):
    """Pop slot i and clear orphaned per-slot widget keys at and after that index
    so subsequent re-renders don't show stale state from the removed slot."""
    if 0 < i < len(st.session_state["resumes"]):
        st.session_state["resumes"].pop(i)
        for _k in list(st.session_state.keys()):
            for _prefix in ("resume_label_", "_resume_uploader_", "_resume_paste_", "_last_resume_hash_"):
                if _k.startswith(_prefix):
                    try:
                        if int(_k[len(_prefix):]) >= i:
                            del st.session_state[_k]
                    except ValueError:
                        pass


def _extract_text_from_upload(uploaded_file):
    """Extract text from a Streamlit uploaded_file. Tries PyPDF2 first, falls
    back to pdfplumber for PDFs PyPDF2 can't read. Returns (text, errors_list)."""
    text = ""
    errors = []
    if uploaded_file.type == "application/pdf":
        text = extract_text_from_pdf(uploaded_file) or ""
        if not text:
            errors.append("PyPDF2 returned empty")
            try:
                import pdfplumber
                uploaded_file.seek(0)
                with pdfplumber.open(uploaded_file) as _pdf:
                    text = "\n".join((p.extract_text() or "") for p in _pdf.pages).strip()
                if not text:
                    errors.append("pdfplumber returned empty")
            except Exception as _e:
                errors.append(f"pdfplumber failed: {type(_e).__name__}: {_e}")
    else:
        try:
            text = str(uploaded_file.getvalue(), "utf-8")
        except Exception as _e:
            errors.append("Text read failed: " + str(_e))
    return text, errors


st.subheader("Your resume(s)")
st.caption(
    "Upload up to 3 versions (e.g. one tailored for sales roles, another for "
    "technical roles). Each match in your daily email and instant scans will "
    "tell you which version to send. The first slot drives the form pre-fill below."
)

for _i in range(len(st.session_state["resumes"])):
    _slot = st.session_state["resumes"][_i]
    _is_primary = (_i == 0)

    with st.container(border=True):
        _hdr_l, _hdr_r = st.columns([5, 1])
        with _hdr_l:
            _hdr_text = f"**Resume {_i + 1}**"
            if _is_primary:
                _hdr_text += "  ·  *Primary — used to pre-fill the form below*"
            st.markdown(_hdr_text)
        with _hdr_r:
            if not _is_primary:
                st.button("Remove", key=f"remove_resume_{_i}",
                          on_click=_remove_resume_slot, args=(_i,))

        # Initialize the label widget from the slot dict on first render of this slot
        if f"resume_label_{_i}" not in st.session_state:
            st.session_state[f"resume_label_{_i}"] = _slot.get("label", "")
        st.text_input(
            "Label",
            key=f"resume_label_{_i}",
            placeholder="e.g. Enterprise AE, Backend Engineer (auto-suggested on upload)",
        )

        _col_up, _col_paste = st.columns(2)
        with _col_up:
            _slot_file = st.file_uploader(
                "Upload PDF or TXT",
                type=["pdf", "txt"],
                key=f"_resume_uploader_{_i}",
            )
        with _col_paste:
            _slot_paste = st.text_area(
                "Or paste text",
                placeholder="Paste resume text here...",
                height=100,
                key=f"_resume_paste_{_i}",
            )

        # Per-slot stable hash so we only re-parse when content actually changes.
        _slot_hash = None
        if _slot_file is not None:
            _slot_hash = f"file:{_slot_file.name}:{_slot_file.size}"
        elif _slot_paste and _slot_paste.strip():
            _slot_hash = f"paste:{hash(_slot_paste.strip())}"

        _last_hash_key = f"_last_resume_hash_{_i}"
        _new_in_slot = (
            _slot_hash is not None
            and _slot_hash != st.session_state.get(_last_hash_key)
        )

        if _new_in_slot:
            if _slot_file is not None:
                _text, _errors = _extract_text_from_upload(_slot_file)
            else:
                _text, _errors = _slot_paste.strip(), []

            if not _text:
                st.error(
                    "Couldn't extract any text. Try re-exporting from Word/Google Docs, "
                    "or paste the text manually."
                )
                for _e in _errors:
                    st.caption(_e)
            else:
                with st.spinner("Analyzing this resume with AI..."):
                    _summary = grader.summarize_resume(_text)
                    # Only suggest a label if the user hasn't already typed one for this slot
                    _existing_label = (st.session_state.get(f"resume_label_{_i}") or "").strip()
                    _suggested_label = "" if _existing_label else grader.suggest_resume_label(_text)
                    # Slot 0 (Primary) also drives form-field pre-fill
                    _parsed = grader.parse_resume_to_profile(_text) if _is_primary else {}

                # Update slot dict
                _slot["text"] = _text
                _slot["summary"] = _summary or ""
                if _suggested_label:
                    _slot["label"] = _suggested_label
                    st.session_state[f"resume_label_{_i}"] = _suggested_label

                # Slot 0: pre-fill form fields with the existing shadow-key logic
                if _is_primary:
                    if _parsed:
                        _FIELD_MAP = {
                            "full_name_input":          ("full_name",          ""),
                            "target_titles_input":      ("target_titles",      ""),
                            "preferred_locations_input":("preferred_locations",""),
                            "min_salary_input":         ("min_salary",         0),
                            "looking_for_input":        ("looking_for",        ""),
                        }
                        _filled = []
                        for _key, (_src, _default) in _FIELD_MAP.items():
                            _val = _parsed.get(_src)
                            if not _val:
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
                                st.session_state[_key] = _val
                                st.session_state[_shadow_key] = _val
                                _filled.append(_src)
                        if _filled:
                            _names = {
                                "full_name": "name",
                                "target_titles": "target titles",
                                "preferred_locations": "location",
                                "min_salary": "salary",
                                "looking_for": "what you're looking for",
                            }
                            st.success(
                                "Pre-filled from your primary resume: "
                                + ", ".join(_names.get(f, f) for f in _filled)
                                + ". Review and edit below before saving."
                            )
                        else:
                            st.info(
                                "Primary resume analyzed — no new fields pre-filled "
                                "(you've already typed values for everything it could suggest)."
                            )
                    else:
                        st.info(
                            "Couldn't auto-parse the primary resume "
                            "(AI parser may be rate-limited). Fill in the form manually below."
                        )
                else:
                    if _summary:
                        st.success(f"Resume {_i + 1} summarized and ready.")
                    else:
                        st.info(
                            "Resume saved, but AI summary couldn't be generated "
                            "(rate-limited or quota exhausted). The grader will still "
                            "use the raw text."
                        )

            st.session_state[_last_hash_key] = _slot_hash

        # Sync the label widget value back into the slot dict every render
        # so user-typed labels are captured before save.
        _slot["label"] = (st.session_state.get(f"resume_label_{_i}") or "").strip() or _slot.get("label", "")

# Add another button (capped at 3 slots)
if len(st.session_state["resumes"]) < 3:
    st.button("+ Add another resume", on_click=_add_resume_slot)

# Mirror the primary slot's text + summary to the legacy stash keys that the
# save handler reads. Keeps backwards compat with the rest of the app while
# Commit 2 wires the full resumes array into the grader.
_primary = st.session_state["resumes"][0] if st.session_state["resumes"] else {}
st.session_state["resume_text_stash"] = _primary.get("text", "")
st.session_state["resume_summary_stash"] = _primary.get("summary") or "No resume provided"

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
    industries = st.text_input("Preferred industries (optional)",
                               placeholder="e.g. SaaS, Hospitality Tech, Payments",
                               key="preferred_industries_input")
    target_companies = st.text_area(
        "Companies you'd love to work at (optional, comma-separated)",
        placeholder="e.g. Stripe, Anthropic, Toast",
        key="target_companies_input",
        height=70,
    )
    col_sal, col_ote = st.columns(2)
    with col_sal:
        salary = st.number_input("Minimum base salary (annual)",
                                 min_value=0, step=5000,
                                 key="min_salary_input")
    with col_ote:
        target_ote = st.number_input(
            "Target total comp / OTE (optional)",
            min_value=0, step=5000,
            key="target_ote_input",
            help="Total expected compensation including commission/bonus. Leave 0 if base salary is the only number that matters.",
        )
    job_type = st.selectbox("Job type", ["Remote", "On-site", "Hybrid"],
                            key="job_type_input")
    match_threshold = st.slider(
        "Match selectivity",
        min_value=30, max_value=95, step=5,
        key="match_threshold_input",
        help="Minimum match score (0-100) for a job to make the cut. "
             "50 = loose (more matches, more noise). "
             "75 = balanced. "
             "85 = strict (only the strongest fits).",
    )
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
                "preferred_industries": industries,
                "target_companies": target_companies,
                "min_salary": salary,
                "target_ote": target_ote,
                "match_threshold": match_threshold,
                "job_type": job_type,
                "looking_for": looking_for,
                "dealbreakers": dealbreakers,
                "resume_summary": resume_summary,
                "resume_text": resume_text,
                "resumes": st.session_state.get("resumes") or [],
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
                jobs = pre_filter(raw_jobs, title_list)
                # Hard-exclude scam patterns + user's dealbreaker phrases (saves LLM tokens)
                _dbreakers = ud.get("dealbreakers", "")
                _before = len(jobs)
                jobs = [j for j in jobs if not reject_bad_fit(j, _dbreakers)]
                if _before > len(jobs):
                    st.caption(
                        f"Filtered out {_before - len(jobs)} jobs "
                        "matching your dealbreakers or scam patterns."
                    )
                # Remove jobs already sent in the last 14 days
                jobs = filter_unsent_jobs(user_email, jobs)
                # Rule-based pre-score so we send the best 50 to the AI grader
                # (huge LLM-cost win on broad scans). Sort high-to-low; truncate.
                _profile_for_score = {
                    "target_titles":        ud.get("target_titles", ""),
                    "preferred_industries": ud.get("preferred_industries", ""),
                    "preferred_locations":  ud.get("preferred_locations", ""),
                    "target_companies":     ud.get("target_companies", ""),
                    "min_salary":           ud.get("min_salary", 0),
                }
                for _j in jobs:
                    _j["rule_score"] = rule_based_score(_j, _profile_for_score)
                jobs.sort(key=lambda j: j.get("rule_score", 0), reverse=True)
                jobs = jobs[:50]
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
                    "preferred_industries": ud.get("preferred_industries", ""),
                    "target_companies": ud.get("target_companies", ""),
                    "min_salary": ud.get("min_salary", 0),
                    "target_ote": ud.get("target_ote", 0),
                    "match_threshold": ud.get("match_threshold", 50),
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
                        score = int(g.get("match_score", 0) or 0)
                        action = g.get("recommended_action") or "Maybe"
                        rec_resume = (g.get("recommended_resume") or "").strip()
                        narrative = (g.get("narrative") or "").strip()
                        role_summary = (g.get("role_summary") or "").strip()
                        reasons = [r for r in (g.get("match_reasons") or []) if r and r.strip()]
                        cautions = [c for c in (g.get("caution_flags") or []) if c and c.strip()]
                        title_text = job.get("title", "Untitled")
                        company_text = job.get("company", "Unknown")

                        # Color-coded action prefix in the expander title
                        _emoji = {"Apply": "\u2705", "Maybe": "\U0001F914", "Skip": "\u26d4"}.get(action, "")
                        with st.expander(
                            f"{_emoji} {action}  \u00b7  {score}/100  \u2014  {title_text} at {company_text}"
                        ):
                            # 1. Narrative first — the "handpicked for you" hook
                            if narrative:
                                st.markdown(
                                    f"> *{narrative}*"
                                )
                            # Recommended resume (only if user has multiple)
                            if rec_resume:
                                st.markdown(f"📎 **Recommended resume to send:** `{rec_resume}`")
                            # 2. Meta row: location, source, apply link
                            meta_col, link_col = st.columns([3, 1])
                            with meta_col:
                                st.caption(
                                    f"{company_text} &middot; "
                                    f"{job.get('location', 'N/A')} &middot; "
                                    f"{job.get('source', 'Unknown')}"
                                )
                            with link_col:
                                if job.get("url"):
                                    st.markdown(
                                        f"[\u27A1 Apply / View]({job.get('url')})"
                                    )
                            # 3. Role summary
                            if role_summary:
                                st.markdown(f"**What this role is:** {role_summary}")
                            # 4. Match reasons
                            if reasons:
                                st.markdown("**Why this fits you:**")
                                for r in reasons:
                                    st.markdown(f"- {r}")
                            # 5. Caution flags (if any)
                            if cautions:
                                st.warning(
                                    "**Watch for:** " + " &middot; ".join(cautions)
                                )
                            # 6. Optional description preview
                            desc_snippet = clean_description(job.get("description", ""))
                            if desc_snippet and desc_snippet != "No description available.":
                                st.caption("**Job listing preview:** " + desc_snippet)
                            if job.get("url"):
                                st.markdown(
                                    f"[Open full listing on {job.get('source', 'source')} "
                                    f"\u2197]({job.get('url')})"
                                )
                else:
                    _user_threshold = ud.get("match_threshold", 50)
                    st.info(
                        f"No jobs scored {_user_threshold} or higher. "
                        "Try broadening your titles, loosening dealbreakers, "
                        "lowering the match-selectivity slider, or scanning again later."
                    )

                if graveyard:
                    with st.expander(
                        "Skipped / Low-Score Jobs (" + str(len(graveyard)) + ")"
                    ):
                        for job in graveyard:
                            g = job.get("grade", {})
                            score = int(g.get("match_score", 0) or 0)
                            summary = (g.get("role_summary") or "").strip()
                            # Fall back to first caution if no role_summary
                            if not summary:
                                cauts = [c for c in (g.get("caution_flags") or []) if c]
                                summary = cauts[0] if cauts else "No summary"
                            link = ""
                            if job.get("url"):
                                link = f" \u2014 [View]({job.get('url')})"
                            st.markdown(
                                f"- **{job.get('title', '')}** at "
                                f"{job.get('company', '')} "
                                f"({job.get('source', '')}) \u2014 "
                                f"{score}/100 \u2014 {summary}{link}"
                            )
