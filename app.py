import streamlit as st
import requests
import json
import os
from datetime import date
from supabase import create_client
from google import genai
from dotenv import load_dotenv

load_dotenv()

# ── Supabase client ──────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# ── Gemini client ────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ── API keys ─────────────────────────────────────────────────────────────────
ADZUNA_APP_ID  = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
RAPIDAPI_KEY   = os.getenv("RAPIDAPI_KEY", "")
SERPAPI_KEY    = os.getenv("SERPAPI_KEY", "")

# ─────────────────────────────────────────────────────────────────────────────
# JOB SOURCES
# ─────────────────────────────────────────────────────────────────────────────

def fetch_adzuna(titles: list[str], locations: list[str]) -> list[dict]:
    jobs = []
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return jobs
    for title in titles[:2]:
        for loc in locations[:2]:
            try:
                params = {
                    "app_id": ADZUNA_APP_ID,
                    "app_key": ADZUNA_APP_KEY,
                    "results_per_page": 10,
                    "what": title,
                    "where": loc,
                    "content-type": "application/json",
                }
                r = requests.get(
                    "https://api.adzuna.com/v1/api/jobs/us/search/1",
                    params=params, timeout=10
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
            except Exception:
                pass
    return jobs


def fetch_themuse(titles: list[str]) -> list[dict]:
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
        except Exception:
            pass
    return jobs


def fetch_remoteok(titles: list[str]) -> list[dict]:
    jobs = []
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "job-agent/1.0"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            for j in data[1:]:  # first item is metadata
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
    except Exception:
        pass
    return jobs


def fetch_jsearch(titles: list[str], locations: list[str]) -> list[dict]:
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
        except Exception:
            pass
    return jobs


def fetch_serpapi_google_jobs(titles: list[str], locations: list[str]) -> list[dict]:
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
        except Exception:
            pass
    return jobs


def deduplicate(jobs: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for j in jobs:
        key = (j["title"].lower().strip(), j["company"].lower().strip())
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI GRADER
# ─────────────────────────────────────────────────────────────────────────────

def grade_job(job: dict, profile: dict) -> dict:
    """Return grading dict from Gemini. Falls back to a neutral grade on error."""
    if not gemini_client:
        return {"rating": 0, "label": "SKIP", "reason": "Gemini not configured.", "commission_trap": False}

    prompt = f"""You are a ruthless job screener. Grade this job for {profile.get('full_name','the user')} who is targeting {profile.get('target_titles','')} in {profile.get('preferred_locations','')} with minimum base salary of {profile.get('min_salary', 0)}. Their ideal role: {profile.get('ideal_role_summary','')}

Job: {job['title']} at {job['company']}. Location: {job['location']}. Description: {job['description']}

COMMISSION TRAP RULE: If base salary appears to be less than 50% of total comp (commission-heavy, OTE-based, draw-based), return rating 0 and flag as Commission Trap.

Return JSON only — no markdown, no explanation outside the JSON:
{{"rating": 1-5, "label": "STRATEGIC|PROFESSIONAL|SKIP", "reason": "one sentence", "commission_trap": true|false}}"""

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        # Strip possible markdown code fences
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        return {"rating": 0, "label": "SKIP", "reason": f"Grading error: {e}", "commission_trap": False}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def stars(rating: int) -> str:
    filled = "★" * rating
    empty  = "☆" * (5 - rating)
    return filled + empty


def get_query_email() -> str:
    """Read ?email= from the URL query params."""
    params = st.query_params
    return params.get("email", "")


def load_profile(email: str) -> dict:
    if not supabase or not email:
        return {}
    try:
        result = supabase.table("profiles").select("*").eq("email", email).execute()
        if result.data:
            return result.data[0]
    except Exception:
        pass
    return {}


def save_profile(data: dict) -> bool:
    if not supabase:
        st.error("Supabase not configured. Check your .env file.")
        return False
    try:
        supabase.table("profiles").upsert(data, on_conflict="email").execute()
        return True
    except Exception as e:
        st.error(f"Save failed: {e}")
        return False


def extract_text(file) -> str:
    raw = file.read()
    try:
        return raw.decode("utf-8")
    except Exception:
        return raw.decode("latin-1", errors="replace")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Job Match Agent", layout="centered")

st.markdown(
    """
    <style>
    .stApp { max-width: 780px; margin: auto; }
    .star-block { font-size: 1.4rem; }
    .label-strategic { color: #1a8c4e; font-weight: 700; }
    .label-professional { color: #1565c0; font-weight: 700; }
    .label-trap { color: #c62828; font-weight: 700; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Job Match Agent")
st.caption("Tell us what you're looking for — we'll do the searching.")

# ── Pre-fill from URL param ──────────────────────────────────────────────────
prefill_email = get_query_email()
existing = load_profile(prefill_email) if prefill_email else {}

# ── Profile form ─────────────────────────────────────────────────────────────
with st.form("profile_form"):
    st.subheader("Your Profile")

    full_name = st.text_input("Full name", value=existing.get("full_name", ""))
    email = st.text_input(
        "Email address (daily matches sent here)",
        value=existing.get("email", prefill_email),
    )
    uploaded_file = st.file_uploader("Upload your resume (PDF or TXT)", type=["pdf", "txt"])
    target_titles = st.text_input(
        "Job title(s) you're targeting (comma-separated)",
        value=existing.get("target_titles", ""),
        placeholder="e.g. Product Manager, Senior Product Manager",
    )
    preferred_locations = st.text_input(
        "Preferred location(s) (comma-separated)",
        value=existing.get("preferred_locations", ""),
        placeholder="e.g. New York, Remote",
    )
    min_salary = st.number_input(
        "Minimum base salary (annual)",
        min_value=0,
        step=5000,
        value=int(existing.get("min_salary", 0)),
    )
    preferred_industries = st.text_input(
        "Preferred industries (comma-separated)",
        value=existing.get("preferred_industries", ""),
        placeholder="e.g. FinTech, SaaS, Healthcare",
    )
    job_type = st.selectbox(
        "Job type preference",
        ["Any", "Remote", "Hybrid", "On-site"],
        index=["Any", "Remote", "Hybrid", "On-site"].index(existing.get("job_type", "Any")),
    )
    ideal_role_summary = st.text_area(
        "Brief summary of your ideal role",
        value=existing.get("ideal_role_summary", ""),
        placeholder="Describe the kind of role, team, and impact you're looking for...",
        height=120,
    )

    submitted = st.form_submit_button("Save Profile", use_container_width=True)

# ── Handle form save ─────────────────────────────────────────────────────────
if submitted:
    if not email:
        st.error("Email is required.")
    else:
        resume_text = existing.get("resume_text", "")
        if uploaded_file:
            resume_text = extract_text(uploaded_file)

        profile_data = {
            "email": email.strip().lower(),
            "full_name": full_name,
            "resume_text": resume_text,
            "target_titles": target_titles,
            "preferred_locations": preferred_locations,
            "min_salary": int(min_salary),
            "preferred_industries": preferred_industries,
            "job_type": job_type,
            "ideal_role_summary": ideal_role_summary,
        }

        if save_profile(profile_data):
            st.success("Profile saved!")

            # Build shareable link
            base_url = st.get_option("browser.serverAddress") or "localhost"
            port = st.get_option("browser.serverPort") or 8501
            share_link = f"http://{base_url}:{port}/?email={email.strip().lower()}"

            st.info(f"Share or bookmark this link to return anytime:\n\n`{share_link}`")
            st.code(share_link, language=None)
            st.button(
                "Copy Your Link",
                on_click=st.write,
                args=(f'<script>navigator.clipboard.writeText("{share_link}")</script>',),
                help="Click to copy your personal link to clipboard",
            )

            # Store profile in session for instant jobs
            st.session_state["profile"] = profile_data

# ── Instant Jobs button ───────────────────────────────────────────────────────
st.divider()

if st.button("Get Instant Jobs Now", type="primary", use_container_width=True):
    profile = st.session_state.get("profile") or existing
    if not profile:
        st.warning("Save your profile first so we know what to search for.")
    else:
        titles    = [t.strip() for t in profile.get("target_titles", "").split(",") if t.strip()]
        locations = [l.strip() for l in profile.get("preferred_locations", "").split(",") if l.strip()]

        if not titles:
            st.warning("Add at least one target job title to your profile.")
        else:
            with st.spinner("Searching across all job sources..."):
                raw_jobs = []
                raw_jobs += fetch_adzuna(titles, locations)
                raw_jobs += fetch_themuse(titles)
                raw_jobs += fetch_remoteok(titles)
                raw_jobs += fetch_jsearch(titles, locations)
                raw_jobs += fetch_serpapi_google_jobs(titles, locations)
                jobs = deduplicate(raw_jobs)

            st.write(f"Found **{len(jobs)}** unique listings. Grading with AI...")

            graded = []
            graveyard = []

            progress = st.progress(0)
            for i, job in enumerate(jobs):
                grade = grade_job(job, profile)
                job["grade"] = grade
                rating = grade.get("rating", 0)
                is_trap = grade.get("commission_trap", False)

                if is_trap or rating < 3:
                    graveyard.append(job)
                else:
                    graded.append(job)

                progress.progress((i + 1) / max(len(jobs), 1))

            progress.empty()

            # Sort graded: 5 first, then 4, then 3
            graded.sort(key=lambda j: j["grade"]["rating"], reverse=True)

            # ── Display approved jobs ────────────────────────────────────────
            if graded:
                st.subheader(f"Your Matches — {date.today().strftime('%B %d, %Y')}")
                for job in graded:
                    g = job["grade"]
                    rating = g["rating"]
                    label  = g.get("label", "PROFESSIONAL")
                    reason = g.get("reason", "")

                    label_class = "label-strategic" if label == "STRATEGIC" else "label-professional"
                    label_display = f"[{label}]"

                    with st.container():
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.markdown(f"**{job['title']}** — {job['company']}")
                            st.caption(f"{job['location']} · {job['source']}")
                        with col2:
                            st.markdown(
                                f"<span class='star-block'>{stars(rating)}</span> "
                                f"<span class='{label_class}'>{label_display}</span>",
                                unsafe_allow_html=True,
                            )
                        st.caption(reason)
                        if job.get("url"):
                            st.markdown(f"[Apply →]({job['url']})")
                        st.divider()
            else:
                st.info("No strong matches found this time. Try broadening your target titles or locations.")

            # ── Graveyard (collapsed) ────────────────────────────────────────
            if graveyard:
                with st.expander(f"Graveyard — {len(graveyard)} rejected listings (click to expand)"):
                    for job in graveyard:
                        g = job["grade"]
                        is_trap = g.get("commission_trap", False)
                        reason  = g.get("reason", "Did not meet criteria.")
                        trap_label = " · **Commission Trap**" if is_trap else ""
                        st.markdown(
                            f"~~{job['title']}~~ — {job['company']} · {job['source']}{trap_label}  \n"
                            f"<small>{reason}</small>",
                            unsafe_allow_html=True,
                        )
