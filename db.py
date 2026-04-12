"""
db.py — Supabase client and profile operations.

Shared module used by both app.py (Streamlit UI) and autopilot.py (daily scanner).
Handles all database reads/writes for user profiles.
"""

import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# ── Supabase Client ──────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = (
    create_client(SUPABASE_URL, SUPABASE_KEY)
    if SUPABASE_URL and SUPABASE_KEY
    else None
)


# ── Profile Operations ───────────────────────────────────────────────────────

def load_profile(email: str) -> dict:
    """Load a user profile by email. Returns dict or empty dict."""
    if not supabase or not email:
        return {}
    try:
        result = (
            supabase.table("profiles")
            .select("*")
            .eq("email", email.strip().lower())
            .execute()
        )
        if result.data:
            return result.data[0]
    except Exception as e:
        print(f"[db] Failed to load profile for {email}: {e}")
    return {}


def save_profile(data: dict) -> bool:
    """Upsert a user profile. Returns True on success."""
    if not supabase:
        print("[db] Supabase not configured — check .env file.")
        return False
    try:
        data["email"] = data["email"].strip().lower()
        supabase.table("profiles").upsert(
            data, on_conflict="email"
        ).execute()
        return True
    except Exception as e:
        print(f"[db] Save failed for {data.get('email', '?')}: {e}")
        return False


def load_all_profiles() -> list:
    """Load every profile (used by autopilot to process all users)."""
    if not supabase:
        print("[db] Supabase not configured.")
        return []
    try:
        result = supabase.table("profiles").select("*").execute()
        return result.data or []
    except Exception as e:
        print(f"[db] Failed to load profiles: {e}")
        return []


# ── Sent Jobs Tracking ───────────────────────────────────────────────────────

def was_job_sent(email: str, title: str, company: str) -> bool:
    """Check if a specific job was already emailed to this user."""
    if not supabase:
        return False
    try:
        result = (
            supabase.table("sent_jobs")
            .select("id")
            .eq("user_email", email.strip().lower())
            .eq("job_title", title.strip().lower())
            .eq("company", company.strip().lower())
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception:
        return False


def mark_jobs_sent(email: str, jobs: list) -> None:
    """Record that these jobs have been emailed to this user."""
    if not supabase or not jobs:
        return
    email = email.strip().lower()
    rows = [
        {
            "user_email": email,
            "job_title": job.get("title", "").strip().lower(),
            "company": job.get("company", "").strip().lower(),
            "source": job.get("source", ""),
        }
        for job in jobs
    ]
    try:
        supabase.table("sent_jobs").insert(rows).execute()
    except Exception as e:
        print(f"[db] Failed to record sent jobs for {email}: {e}")


def filter_unsent_jobs(email: str, jobs: list) -> list:
    """Return only jobs that haven't been emailed to this user yet."""
    return [
        job for job in jobs
        if not was_job_sent(email, job.get("title", ""), job.get("company", ""))
    ]
