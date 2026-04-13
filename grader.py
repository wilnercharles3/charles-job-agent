"""
grader.py - AI grading with Gemini, resume summarization, and batch processing.

Shared module used by both app.py and autopilot.py.
Handles all Gemini AI interactions: resume summarization and job grading.
"""

import json
import os
import time
from google import genai
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

MODEL = "gemini-2.0-flash"
GRADE_DELAY = 1.5  # seconds between grading calls
BATCH_SIZE = 3     # jobs per grading call


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
        response = gemini.models.generate_content(
            model=MODEL, contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"[grader] Resume summary failed: {e}")
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


def grade_single(job: dict, profile: dict) -> dict:
    """Grade a single job. Returns grading dict."""
    if not gemini:
        return {"rating": 0, "label": "SKIP", "reason": "AI grader not configured.", "commission_trap": False}

    prompt = _build_grade_prompt(job, profile)

    for attempt in range(3):
        try:
            response = gemini.models.generate_content(
                model=MODEL, contents=prompt
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
            return json.loads(text)
        except Exception as e:
            print(f"[grader] Attempt {attempt + 1} failed: {e}")
            time.sleep(2)

    return {"rating": 0, "label": "SKIP", "reason": "Grading failed after retries.", "commission_trap": False}


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
    """Grade a batch of jobs in a single API call."""
    if not gemini:
        return [{"rating": 0, "label": "SKIP", "reason": "AI grader not configured.", "commission_trap": False}] * len(jobs_batch)

    prompt = _build_batch_prompt(jobs_batch, profile)

    for attempt in range(3):
        try:
            response = gemini.models.generate_content(
                model=MODEL, contents=prompt
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
            results = json.loads(text)
            if isinstance(results, list) and len(results) == len(jobs_batch):
                return results
            break
        except Exception as e:
            print(f"[grader] Batch attempt {attempt + 1} failed: {e}")
            time.sleep(2)

    # Fallback: grade individually
    return [grade_single(job, profile) for job in jobs_batch]


# -- Main Grading Entry Point ------------------------------------------------

def grade_all_jobs(jobs: list, profile: dict, on_progress=None) -> tuple:
    """
    Grade all jobs using batched API calls.
    Returns (approved_jobs, graveyard_jobs).
    on_progress(current, total) is called after each batch if provided.
    """
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

        # Rate limit delay between batches
        if i + BATCH_SIZE < total:
            time.sleep(GRADE_DELAY)

    # Sort approved: highest rated first
    approved.sort(key=lambda j: j["grade"].get("rating", 0), reverse=True)

    return approved, graveyard
