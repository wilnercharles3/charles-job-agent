"""
grader.py - AI grading with Gemini, resume summarization, and batch processing.

Shared module used by both app.py and autopilot.py.
Handles all Gemini AI interactions: resume summarization and job grading.
"""

import json
import os
import re
import time
from google import genai
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

MODEL = "gemini-2.5-flash-lite"  # higher free-tier quota than 2.0-flash
GRADE_DELAY = 1.5   # seconds between grading calls
BATCH_SIZE = 3      # jobs per grading call
MAX_429_WAIT = 30   # max seconds to wait on a rate-limit hint before giving up

# Module-level quota kill switch. Reset per grade_all_jobs() invocation so
# repeated UI scans after a cool-down get another chance.
_quota_dead = False


class QuotaExhausted(Exception):
    """Raised when Gemini reports free-tier quota is 0 (not just throttled)."""


def _parse_retry_delay(err_msg: str) -> float | None:
    """Extract 'Please retry in 2.30s' hint from a Gemini error message."""
    m = re.search(r'retry in (\d+(?:\.\d+)?)s', err_msg)
    return float(m.group(1)) if m else None


def _call_gemini(prompt: str, max_wait: float = MAX_429_WAIT) -> str:
    """Single Gemini call with smart 429 handling.

    - On hard quota kill (limit: 0 on free-tier): trip _quota_dead, raise QuotaExhausted.
    - On soft 429 with retry hint: wait the hinted duration once, retry, then give up.
    - On other errors: one-line log, re-raise.
    - Returns the raw response.text.
    """
    global _quota_dead
    if _quota_dead:
        raise QuotaExhausted("Free-tier quota exhausted this run")
    if not gemini:
        raise RuntimeError("Gemini client not configured")

    for attempt in (1, 2):
        try:
            r = gemini.models.generate_content(model=MODEL, contents=prompt)
            return r.text
        except Exception as e:
            msg = str(e)
            if "limit: 0" in msg and "free_tier" in msg:
                _quota_dead = True
                print("[grader] Gemini free-tier quota exhausted — short-circuiting.")
                raise QuotaExhausted(msg) from e
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                hint = _parse_retry_delay(msg)
                if attempt == 1 and hint is not None and hint <= max_wait:
                    print(f"[grader] 429, waiting {hint:.0f}s (server hint)")
                    time.sleep(hint)
                    continue
                print(f"[grader] 429, giving up (hint={hint}, max_wait={max_wait})")
                raise
            print(f"[grader] Error: {msg[:140]}")
            raise

    raise RuntimeError("unreachable")


# -- Resume Summarization (runs once on upload, stored in Supabase) ----------

def summarize_resume(resume_text: str) -> str:
    """
    Generate a compact summary of the user's resume for use in job matching.
    Extracts key skills, experience level, industries, and strengths.
    This runs silently in the background when the user uploads a resume.
    """
    if not gemini or not resume_text or len(resume_text.strip()) < 50:
        return ""

    prompt = (
        "You are a career analyst. Read this resume and produce a concise "
        "summary (150-200 words max) that captures:\n"
        "- Top skills and technologies\n"
        "- Years/level of experience\n"
        "- Industries and domains worked in\n"
        "- Key strengths and standout qualifications\n"
        "- Type of roles they are best suited for\n\n"
        "Write in third person. No bullet points, just a tight paragraph.\n\n"
        f"RESUME:\n{resume_text[:3000]}"
    )

    try:
        text = _call_gemini(prompt)
        return text.strip()
    except QuotaExhausted:
        return ""
    except Exception as e:
        print(f"[grader] Resume summary failed: {str(e)[:140]}")
        return ""


# -- Single Job Grading ------------------------------------------------------

def _build_grade_prompt(job: dict, profile: dict) -> str:
    """Build the grading prompt for a single job."""
    name = profile.get("full_name", "the user")
    titles = profile.get("target_titles", "")
    locations = profile.get("preferred_locations", "")
    salary = profile.get("min_salary", 0)
    looking_for = profile.get("looking_for", "")
    dealbreakers = profile.get("dealbreakers", "")
    resume_summary = profile.get("resume_summary", "")

    return f"""You are an expert job matching advisor. Grade this job for {name}.

CANDIDATE PROFILE:
- Targeting roles: {titles}
- Preferred locations: {locations}
- Minimum base salary: ${salary:,}
- What they want: {looking_for}
- Dealbreakers: {dealbreakers}
- Resume summary: {resume_summary}

JOB LISTING:
- Title: {job.get('title', '')}
- Company: {job.get('company', '')}
- Location: {job.get('location', '')}
- Source: {job.get('source', '')}
- Description: {job.get('description', '')}

GRADING RULES:
1. Rate 1-5 based on how well this job matches the candidate.
2. Label as STRATEGIC (strong match, 4-5), PROFESSIONAL (decent match, 3), or SKIP (poor match, 1-2).
3. COMMISSION TRAP: If base salary appears less than 50% of total comp, set commission_trap to true.
4. If any dealbreaker is clearly violated, rate 1-2 and label SKIP.
5. For the reason field:
   - STRATEGIC (4-5): Be enthusiastic and specific about why this is a great fit.
   - PROFESSIONAL (3): Encouraging but honest about gaps.
   - SKIP (1-2): Brief and clear about why it does not match.

Return ONLY valid JSON, no markdown fences:
{{\"rating\": 1-5, \"label\": \"STRATEGIC|PROFESSIONAL|SKIP\", \"reason\": \"your detailed assessment\", \"commission_trap\": true|false}}"""


RATE_LIMITED_GRADE = {
    "rating": 0, "label": "SKIP",
    "reason": "AI grader is temporarily rate-limited. Try again in a few minutes.",
    "commission_trap": False,
}
FAILED_GRADE = {
    "rating": 0, "label": "SKIP",
    "reason": "Grading failed.",
    "commission_trap": False,
}
UNCONFIGURED_GRADE = {
    "rating": 0, "label": "SKIP",
    "reason": "AI grader not configured.",
    "commission_trap": False,
}


def _clean_json_response(text: str) -> str:
    """Strip markdown fences and leading 'json' tag from an LLM JSON response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
    if text.startswith("json"):
        text = text[4:]
    return text.strip()


def grade_single(job: dict, profile: dict) -> dict:
    """Grade a single job. Returns grading dict."""
    if not gemini:
        return dict(UNCONFIGURED_GRADE)

    prompt = _build_grade_prompt(job, profile)
    try:
        text = _call_gemini(prompt)
        return json.loads(_clean_json_response(text))
    except QuotaExhausted:
        return dict(RATE_LIMITED_GRADE)
    except Exception as e:
        print(f"[grader] grade_single failed: {str(e)[:140]}")
        return dict(FAILED_GRADE)


# -- Batch Grading -----------------------------------------------------------

def _build_batch_prompt(jobs_batch: list, profile: dict) -> str:
    """Build a prompt that grades multiple jobs at once."""
    name = profile.get("full_name", "the user")
    titles = profile.get("target_titles", "")
    locations = profile.get("preferred_locations", "")
    salary = profile.get("min_salary", 0)
    looking_for = profile.get("looking_for", "")
    dealbreakers = profile.get("dealbreakers", "")
    resume_summary = profile.get("resume_summary", "")

    jobs_text = ""
    for i, job in enumerate(jobs_batch):
        jobs_text += f"""
JOB {i + 1}:
- Title: {job.get('title', '')}
- Company: {job.get('company', '')}
- Location: {job.get('location', '')}
- Source: {job.get('source', '')}
- Description: {job.get('description', '')}
"""

    return f"""You are an expert job matching advisor. Grade these {len(jobs_batch)} jobs for {name}.

CANDIDATE PROFILE:
- Targeting roles: {titles}
- Preferred locations: {locations}
- Minimum base salary: ${salary:,}
- What they want: {looking_for}
- Dealbreakers: {dealbreakers}
- Resume summary: {resume_summary}

{jobs_text}

GRADING RULES:
1. Rate each job 1-5 based on match quality.
2. Label as STRATEGIC (4-5), PROFESSIONAL (3), or SKIP (1-2).
3. COMMISSION TRAP: If base salary appears less than 50% of total comp, set commission_trap to true.
4. If any dealbreaker is violated, rate 1-2 and SKIP.
5. For reasons: STRATEGIC = enthusiastic and specific. PROFESSIONAL = encouraging but honest. SKIP = brief and clear.

Return ONLY a JSON array with one object per job, in order:
[{{\"rating\": 1-5, \"label\": \"STRATEGIC|PROFESSIONAL|SKIP\", \"reason\": \"assessment\", \"commission_trap\": true|false}}, ...]"""


def grade_batch(jobs_batch: list, profile: dict) -> list:
    """Grade a batch of jobs in a single API call.

    On quota exhaustion: returns RATE_LIMITED_GRADE for every job (no fallback
    to grade_single — that would just waste more calls).
    On JSON parse error or mismatched length: falls back to grade_single per job
    (each of those also short-circuits via _quota_dead if quota is gone).
    """
    if not gemini:
        return [dict(UNCONFIGURED_GRADE) for _ in jobs_batch]

    prompt = _build_batch_prompt(jobs_batch, profile)
    try:
        text = _call_gemini(prompt)
        results = json.loads(_clean_json_response(text))
        if isinstance(results, list) and len(results) == len(jobs_batch):
            return results
        print(f"[grader] Batch shape mismatch (got {len(results) if isinstance(results, list) else '?'}, expected {len(jobs_batch)}), falling back to individual grading")
    except QuotaExhausted:
        return [dict(RATE_LIMITED_GRADE) for _ in jobs_batch]
    except Exception as e:
        print(f"[grader] grade_batch failed: {str(e)[:140]}, falling back to individual grading")

    # Non-quota failure: try grading each job individually (each respects _quota_dead).
    return [grade_single(job, profile) for job in jobs_batch]


# -- Main Grading Entry Point ------------------------------------------------

def grade_all_jobs(jobs: list, profile: dict, on_progress=None) -> tuple:
    """
    Grade all jobs using batched API calls.
    Returns (approved_jobs, graveyard_jobs, quota_exhausted: bool).
    on_progress(current, total) is called after each batch if provided.
    """
    global _quota_dead
    _quota_dead = False  # reset per invocation — quota may have replenished

    approved = []
    graveyard = []
    total = len(jobs)

    for i in range(0, total, BATCH_SIZE):
        batch = jobs[i:i + BATCH_SIZE]
        grades = grade_batch(batch, profile)

        for job, grade in zip(batch, grades):
            job["grade"] = grade
            rating = grade.get("rating", 0)
            is_trap = grade.get("commission_trap", False)

            if is_trap or rating < 3:
                graveyard.append(job)
            else:
                approved.append(job)

        if on_progress:
            on_progress(min(i + BATCH_SIZE, total), total)

        # If quota died mid-loop, mark remaining jobs as rate-limited and stop.
        if _quota_dead and i + BATCH_SIZE < total:
            for remaining in jobs[i + BATCH_SIZE:]:
                remaining["grade"] = dict(RATE_LIMITED_GRADE)
                graveyard.append(remaining)
            break

        # Rate limit delay between batches
        if i + BATCH_SIZE < total:
            time.sleep(GRADE_DELAY)

    # Sort approved: highest rated first
    approved.sort(key=lambda j: j["grade"].get("rating", 0), reverse=True)

    return approved, graveyard, _quota_dead
