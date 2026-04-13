"""
app.py - Job Match Agent: Profile Intake Form

A clean Streamlit form where users enter their job preferences.
Profile data is saved to Supabase. Resume is summarized by AI in the background.
All job searching and delivery happens via autopilot.py and email.
"""

import re
import streamlit as st
from db import load_profile, save_profile
from grader import summarize_resume


# -- Page Config -------------------------------------------------------------

st.set_page_config(page_title="Job Match Agent", layout="centered")

st.markdown("""
<style>
 .stApp { max-width: 720px; margin: auto; }
 .success-box {
 background: #e8f5e9; border-radius: 10px; padding: 24px;
 text-align: center; margin-top: 16px;
 }
 .success-box h3 { color: #2e7d32; margin-bottom: 8px; }
</style>
""", unsafe_allow_html=True)


# -- Helpers -----------------------------------------------------------------

def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def extract_text(file) -> str:
    """Extract text from an uploaded PDF or TXT file."""
    raw = file.read()
    try:
        return raw.decode("utf-8")
    except Exception:
        return raw.decode("latin-1", errors="replace")


def parse_comma_list(text: str) -> list:
    """Split comma-separated input into a clean list."""
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


# -- Load existing profile from URL param ------------------------------------

params = st.query_params
prefill_email = params.get("email", "")
existing = load_profile(prefill_email) if prefill_email else {}


# -- Header ------------------------------------------------------------------

st.title("Job Match Agent")
st.caption(
    "Fill out your profile below. You'll receive daily job matches "
    "by email \u2014 tailored to your resume, preferences, and goals."
)

if existing:
    st.success("Welcome back! Your profile is loaded. Update anything and save.")


# -- Profile Form ------------------------------------------------------------

with st.form("profile_form"):
    st.subheader("Your Info")

    full_name = st.text_input(
        "Full name",
        value=existing.get("full_name", ""),
    )

    email = st.text_input(
        "Email address (daily matches sent here)",
        value=existing.get("email", prefill_email or ""),
    )

    uploaded_file = st.file_uploader(
        "Upload your resume (PDF or TXT)",
        type=["pdf", "txt"],
        help="Your resume helps our AI find better matches. It's analyzed once and never shared.",
    )

    st.divider()
    st.subheader("What You're Looking For")

    target_titles = st.text_input(
        "Job title(s) you're targeting",
        value=existing.get("target_titles", ""),
        placeholder="e.g. Product Manager, Senior Product Manager",
        help="Comma-separated. These are used to search job boards.",
    )

    preferred_locations = st.text_input(
        "Preferred location(s)",
        value=existing.get("preferred_locations", ""),
        placeholder="e.g. New York, Remote, Chicago",
        help="Comma-separated. Include 'Remote' if you're open to it.",
    )

    min_salary = st.number_input(
        "Minimum base salary (annual)",
        min_value=0,
        step=5000,
        value=int(existing.get("min_salary", 50000)),
    )

    job_type = st.selectbox(
        "Job type preference",
        ["Any", "Remote", "Hybrid", "On-site"],
        index=["Any", "Remote", "Hybrid", "On-site"].index(
            existing.get("job_type", "Any")
        ),
    )

    looking_for = st.text_area(
        "Tell us what you're looking for",
        value=existing.get("looking_for", ""),
        placeholder=(
            "What matters to you? E.g. I want a remote role at a startup, "
            "no sales or commission jobs, I'm great with data and Python, "
            "I want a team that values mentorship..."
        ),
        height=120,
        help="The more detail you give, the better our AI can match you. Include industries, skills, culture preferences \u2014 anything.",
    )

    dealbreakers = st.text_area(
        "Dealbreakers (optional)",
        value=existing.get("dealbreakers", ""),
        placeholder=(
            "Anything you definitely don't want? E.g. no commission-only, "
            "no overnight shifts, no travel required, no startups under 20 people..."
        ),
        height=80,
        help="Jobs that match your dealbreakers will be filtered out automatically.",
    )

    submitted = st.form_submit_button(
        "Save My Profile", use_container_width=True, type="primary"
    )


# -- Handle Form Submission --------------------------------------------------

if submitted:
    # Validation
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
        # Build profile data
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

        # Save to Supabase
        with st.spinner("Saving your profile..."):
            saved = save_profile(profile_data)

        if saved:
            # Summarize resume in background if new upload
            if uploaded_file and resume_text:
                with st.spinner("Analyzing your resume..."):
                    summary = summarize_resume(resume_text)
                    if summary:
                        profile_data["resume_summary"] = summary
                        save_profile(profile_data)

            # Build return link
            clean_email = email.strip().lower()

            st.markdown(
                f"""
                <div class="success-box">
                    <h3>You're all set!</h3>
                    <p>Daily job matches will be sent to <strong>{clean_email}</strong>.</p>
                    <p style="color: #555; font-size: 14px;">
                        Our AI scans 5 job boards every morning and emails you
                        only the roles that match your profile.
                    </p>
                    <p style="color: #777; font-size: 13px; margin-top: 12px;">
                        Want to update your preferences later? Just come back to this page.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Show bookmark reminder with actual URL
            app_url = st.secrets.get("APP_URL", "")
            if app_url:
                return_link = f"{app_url}?email={clean_email}"
            else:
                return_link = f"?email={clean_email}"
            st.info(
                f"Bookmark this link to update your profile anytime:\n\n"
                f"**{return_link}**"
            )
        else:
            st.error(
                "Something went wrong saving your profile. "
                "Please check your connection and try again."
            )
"""
app.py - Job Match Agent: Profile Intake Form

A clean Streamlit form where users enter their job preferences.
Profile data is saved to Supabase. Resume is summarized by AI in the background.
All job searching and delivery happens via autopilot.py and email.
"""

import re
import streamlit as st
from db import load_profile, save_profile
from grader import summarize_resume


# -- Page Config -------------------------------------------------------------

st.set_page_config(page_title="Job Match Agent", layout="centered")

st.markdown("""
<style>
    .stApp { max-width: 720px; margin: auto; }
    .success-box {
        background: #e8f5e9; border-radius: 10px; padding: 24px;
        text-align: center; margin-top: 16px;
    }
    .success-box h3 { color: #2e7d32; margin-bottom: 8px; }
</style>
""", unsafe_allow_html=True)


# -- Helpers -----------------------------------------------------------------

def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", email))


def extract_text(file) -> str:
    """Extract text from an uploaded PDF or TXT file."""
    raw = file.read()
    try:
        return raw.decode("utf-8")
    except Exception:
        return raw.decode("latin-1", errors="replace")


def parse_comma_list(text: str) -> list:
    """Split comma-separated input into a clean list."""
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


# -- Load existing profile from URL param ------------------------------------

params = st.query_params
prefill_email = params.get("email", "")
existing = load_profile(prefill_email) if prefill_email else {}


# -- Header ------------------------------------------------------------------

st.title("Job Match Agent")
st.caption(
    "Fill out your profile below. You\'ll receive daily job matches "
    "by email \u2014 tailored to your resume, preferences, and goals."
)

if existing:
    st.success("Welcome back! Your profile is loaded. Update anything and save.")


# -- Profile Form ------------------------------------------------------------

with st.form("profile_form"):
    st.subheader("Your Info")

    full_name = st.text_input(
        "Full name",
        value=existing.get("full_name", ""),
    )

    email = st.text_input(
        "Email address (daily matches sent here)",
        value=existing.get("email", prefill_email or ""),
    )

    uploaded_file = st.file_uploader(
        "Upload your resume (PDF or TXT)",
        type=["pdf", "txt"],
        help="Your resume helps our AI find better matches. It\'s analyzed once and never shared.",
    )

    st.divider()
    st.subheader("What You\'re Looking For")

    target_titles = st.text_input(
        "Job title(s) you\'re targeting",
        value=existing.get("target_titles", ""),
        placeholder="e.g. Product Manager, Senior Product Manager",
        help="Comma-separated. These are used to search job boards.",
    )

    preferred_locations = st.text_input(
        "Preferred location(s)",
        value=existing.get("preferred_locations", ""),
        placeholder="e.g. New York, Remote, Chicago",
        help="Comma-separated. Include \'Remote\' if you\'re open to it.",
    )

    min_salary = st.number_input(
        "Minimum base salary (annual)",
        min_value=0,
        step=5000,
        value=int(existing.get("min_salary", 50000)),
    )

    job_type = st.selectbox(
        "Job type preference",
        ["Any", "Remote", "Hybrid", "On-site"],
        index=["Any", "Remote", "Hybrid", "On-site"].index(
            existing.get("job_type", "Any")
        ),
    )

    looking_for = st.text_area(
        "Tell us what you\'re looking for",
        value=existing.get("looking_for", ""),
        placeholder=(
            "What matters to you? E.g. I want a remote role at a startup, "
            "no sales or commission jobs, I\'m great with data and Python, "
            "I want a team that values mentorship..."
        ),
        height=120,
        help="The more detail you give, the better our AI can match you. Include industries, skills, culture preferences \u2014 anything.",
    )

    dealbreakers = st.text_area(
        "Dealbreakers (optional)",
        value=existing.get("dealbreakers", ""),
        placeholder=(
            "Anything you definitely don\'t want? E.g. no commission-only, "
            "no overnight shifts, no travel required, no startups under 20 people..."
        ),
        height=80,
        help="Jobs that match your dealbreakers will be filtered out automatically.",
    )

    submitted = st.form_submit_button(
        "Save My Profile", use_container_width=True, type="primary"
    )


# -- Handle Form Submission --------------------------------------------------

if submitted:
    # Validation
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
        # Build profile data
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

        # Save to Supabase
        with st.spinner("Saving your profile..."):
            saved = save_profile(profile_data)

        if saved:
            # Summarize resume in background if new upload
            if uploaded_file and resume_text:
                with st.spinner("Analyzing your resume..."):
                    summary = summarize_resume(resume_text)
                    if summary:
                        profile_data["resume_summary"] = summary
                        save_profile(profile_data)

            # Build return link
            clean_email = email.strip().lower()

            st.markdown(
                f"""
                <div class="success-box">
                    <h3>You\'re all set!</h3>
                    <p>Daily job matches will be sent to <strong>{clean_email}</strong>.</p>
                    <p style="color: #555; font-size: 14px;">
                        Our AI scans 5 job boards every morning and emails you
                        only the roles that match your profile.
                    </p>
                    <p style="color: #777; font-size: 13px; margin-top: 12px;">
                        Want to update your preferences later? Just come back to this page.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Show bookmark reminder
            st.info(
                f"Bookmark this link to update your profile anytime:\n\n"
                f"**{st.query_params}**"
            )
        else:
            st.error(
                "Something went wrong saving your profile. "
                "Please check your connection and try again."
            )
