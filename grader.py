"""
grader.py - AI grading with multi-LLM fallback chain.

Provider order (each falls back on QuotaExhausted or RuntimeError):
  1. Google Gemini   (GEMINI_API_KEY, default model gemini-2.5-flash-lite)
  2. Anthropic Claude (ANTHROPIC_API_KEY, default claude-haiku-4-5-20251001)
  3. Ollama local    (http://localhost:11434, default gemma3:4b)

Each provider is independently kill-switched per-run so one dead provider
doesn't drag down the others.
"""

import json
import os
import re
import time
import requests
from google import genai
from dotenv import load_dotenv

load_dotenv()

# -- Provider configuration -------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_anthropic_client = None
if ANTHROPIC_API_KEY:
    try:
        from anthropic import Anthropic
        _anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
    except ImportError:
        print("[grader] anthropic package not installed; Anthropic fallback disabled.")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")

GRADE_DELAY = 1.5   # seconds between grading calls
BATCH_SIZE = 3      # jobs per grading call
MAX_429_WAIT = 30   # max seconds to wait on a rate-limit hint before giving up

# Per-provider kill switches. Set when that provider exhausts quota; reset per
# grade_all_jobs() invocation. Skipping a dead provider lets the next in the
# chain take over without retrying-to-fail every call.
_gemini_dead = False
_anthropic_dead = False
_ollama_dead = False

# Legacy alias kept for backwards-compat with any external script that may
# import _quota_dead from this module. Reflects the Gemini status only.
_quota_dead = False


class QuotaExhausted(Exception):
    """Raised when ALL configured LLM providers have exhausted their quota."""


# Substrings that, when present in an error message, indicate the provider's
# quota is exhausted for this run (not just a transient rate-limit). Broader
# than the original Gemini-specific match so today's "You exceeded your current
# quota" wording trips the flag.
_QUOTA_KILL_PATTERNS = (
    "limit: 0",
    "free_tier",
    "exceeded your current quota",
    "exceeded your quota",
    "quotaFailure",
    "rate_limit_exceeded",      # Anthropic phrasing
    "insufficient_quota",       # generic
    "credit balance is too low",  # Anthropic billing-empty wording
    "credits are exhausted",      # OpenAI-style wording
)


def _parse_retry_delay(err_msg: str) -> float | None:
    """Extract 'Please retry in 2.30s' hint from an error message."""
    m = re.search(r'retry in (\d+(?:\.\d+)?)s', err_msg)
    return float(m.group(1)) if m else None


def _is_quota_kill(msg: str) -> bool:
    return any(p in msg for p in _QUOTA_KILL_PATTERNS)


# -- Provider: Gemini -------------------------------------------------------

def _call_gemini(prompt: str, max_wait: float = MAX_429_WAIT) -> str:
    """Single Gemini call with smart 429 handling."""
    global _gemini_dead, _quota_dead
    if _gemini_dead:
        raise QuotaExhausted("Gemini quota exhausted this run")
    if not gemini:
        raise RuntimeError("Gemini client not configured")

    for attempt in (1, 2):
        try:
            r = gemini.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            return r.text
        except Exception as e:
            msg = str(e)
            if _is_quota_kill(msg):
                _gemini_dead = True
                _quota_dead = True  # back-compat alias
                print("[grader] Gemini quota exhausted — falling back to next provider.")
                raise QuotaExhausted(msg) from e
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                hint = _parse_retry_delay(msg)
                if attempt == 1 and hint is not None and hint <= max_wait:
                    print(f"[grader] Gemini 429, waiting {hint:.0f}s (server hint)")
                    time.sleep(hint)
                    continue
                print(f"[grader] Gemini 429, giving up (hint={hint}, max_wait={max_wait})")
                raise
            print(f"[grader] Gemini error: {msg[:140]}")
            raise

    raise RuntimeError("unreachable")


# -- Provider: Anthropic Claude ---------------------------------------------

def _call_anthropic(prompt: str, max_wait: float = MAX_429_WAIT) -> str:
    """Anthropic Claude fallback. Same prompt-in / text-out contract as Gemini."""
    global _anthropic_dead
    if _anthropic_dead:
        raise QuotaExhausted("Anthropic quota exhausted this run")
    if not _anthropic_client:
        raise RuntimeError("Anthropic client not configured (ANTHROPIC_API_KEY unset)")

    for attempt in (1, 2):
        try:
            msg = _anthropic_client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            # content is a list of blocks; first block is text for our prompts
            return msg.content[0].text
        except Exception as e:
            err = str(e)
            if _is_quota_kill(err):
                _anthropic_dead = True
                print("[grader] Anthropic quota exhausted — falling back to next provider.")
                raise QuotaExhausted(err) from e
            if "429" in err or "overloaded" in err.lower():
                hint = _parse_retry_delay(err)
                if attempt == 1 and hint is not None and hint <= max_wait:
                    print(f"[grader] Anthropic 429, waiting {hint:.0f}s")
                    time.sleep(hint)
                    continue
                print(f"[grader] Anthropic 429, giving up")
                raise
            print(f"[grader] Anthropic error: {err[:140]}")
            raise


# -- Provider: Ollama (local) -----------------------------------------------

_ollama_alive_checked = False
_ollama_alive_cached = False


def _ollama_alive() -> bool:
    """Cheap one-second check: is the local Ollama server reachable? Cached."""
    global _ollama_alive_checked, _ollama_alive_cached
    if _ollama_alive_checked:
        return _ollama_alive_cached
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.0)
        _ollama_alive_cached = (r.status_code == 200)
    except Exception:
        _ollama_alive_cached = False
    _ollama_alive_checked = True
    return _ollama_alive_cached


def _call_ollama(prompt: str, max_wait: float = MAX_429_WAIT) -> str:
    """Local Ollama fallback. Slow but free and quota-immune."""
    global _ollama_dead
    if _ollama_dead:
        raise QuotaExhausted("Ollama unavailable this run")
    if not _ollama_alive():
        _ollama_dead = True
        raise RuntimeError("Ollama not reachable at " + OLLAMA_URL)

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_ctx": 8192, "temperature": 0.2},
            },
            timeout=180,
        )
        if r.status_code != 200:
            print(f"[grader] Ollama HTTP {r.status_code}: {r.text[:140]}")
            raise RuntimeError(f"Ollama returned {r.status_code}")
        body = r.json()
        return body.get("response", "")
    except Exception as e:
        print(f"[grader] Ollama error: {str(e)[:140]}")
        raise


# -- Multi-provider router --------------------------------------------------

def _call_llm(prompt: str, max_wait: float = MAX_429_WAIT) -> str:
    """Try each configured LLM provider in order. Return text from the first
    success. Raise QuotaExhausted only if every provider is dead this run."""
    providers = [
        ("gemini", _call_gemini, _gemini_dead),
        ("anthropic", _call_anthropic, _anthropic_dead),
        ("ollama", _call_ollama, _ollama_dead),
    ]
    last_exc: Exception | None = None
    for name, fn, _ in providers:
        try:
            return fn(prompt, max_wait=max_wait)
        except QuotaExhausted as e:
            last_exc = e
            continue  # try next provider
        except RuntimeError as e:
            # Provider not configured or unreachable — skip to next without
            # treating it as a quota event for the chain.
            last_exc = e
            continue
        except Exception as e:
            # Real error on this provider (parse failure, 5xx, etc.). The
            # individual provider already printed a one-line log. Try next.
            last_exc = e
            continue
    # Every provider failed.
    raise QuotaExhausted(
        "All LLM providers unavailable this run. Last error: " + str(last_exc)[:200]
    )


# Backwards-compat alias: any internal callsite that still wants Gemini-only
# can use _call_gemini directly; the new _call_llm is the default.



# -- Resume Parsing (runs on upload to pre-fill form fields) -----------------

def _sanitize_salary(val) -> int:
    """Coerce an LLM-returned salary into an integer. Handles '$130,000', '130k', etc."""
    if isinstance(val, bool):
        return 0
    if isinstance(val, int):
        return max(0, val)
    if isinstance(val, float):
        return max(0, int(val))
    if isinstance(val, str):
        s = val.strip().lower()
        s = s.replace("$", "").replace(",", "").replace("usd", "").replace(" ", "")
        if s.endswith("/year") or s.endswith("/yr"):
            s = s.rsplit("/", 1)[0]
        if s.endswith("k"):
            try:
                return max(0, int(float(s[:-1]) * 1000))
            except ValueError:
                return 0
        try:
            return max(0, int(float(s)))
        except ValueError:
            return 0
    return 0


def suggest_resume_label(resume_text: str) -> str:
    """Propose a 2-4 word label that captures the role focus of a resume.

    Examples: 'Enterprise AE', 'SaaS Sales Specialist', 'Backend Engineer',
    'Hospitality Strategic Account', 'Technical PM'.

    Used by the multi-resume form to pre-populate the Label input on upload.
    Returns "" on quota exhaustion or any error so the UI just leaves the
    label blank for the user to type themselves.
    """
    if not gemini or not resume_text or len(resume_text.strip()) < 50:
        return ""
    prompt = (
        "In 2-4 words, propose a label that describes the role focus or "
        "specialization of this resume. Examples of good labels:\n"
        "- 'Enterprise AE'\n"
        "- 'SaaS Sales Specialist'\n"
        "- 'Backend Engineer'\n"
        "- 'Hospitality Strategic Account'\n"
        "- 'Technical Program Manager'\n"
        "- 'IT Systems Administrator'\n\n"
        "Return ONLY the label. No quotes, no markdown, no explanation, "
        "no punctuation at the end. Just 2-4 words.\n\n"
        f"RESUME:\n{resume_text[:3000]}"
    )
    try:
        text = _call_llm(prompt)
    except QuotaExhausted:
        return ""
    except Exception as e:
        print(f"[grader] suggest_resume_label failed: {str(e)[:140]}")
        return ""
    # Strip any quotes/markdown the LLM included anyway, cap at 40 chars
    label = (text or "").strip().strip('"').strip("'").strip("`").strip()
    if len(label) > 40:
        label = label[:40].rsplit(" ", 1)[0]
    return label


def parse_resume_to_profile(resume_text: str) -> dict:
    """Extract form-pre-fill fields from a resume. Returns {} if parse fails.

    Return keys (all optional; caller decides which to apply):
        full_name, email, target_titles, preferred_locations,
        min_salary (int), looking_for
    """
    if not gemini or not resume_text or len(resume_text.strip()) < 50:
        return {}

    prompt = (
        "You are a resume analyst pre-filling a job-search form. The resume "
        "below is from a professional job seeker. Make concrete, realistic "
        "estimates — do NOT hedge with generic titles or salary 0 when the "
        "resume gives you enough signal to be specific.\n\n"
        "Return ONLY valid JSON, no markdown fences, with these exact keys:\n"
        "{\n"
        '  "full_name": "candidate full name, or empty string",\n'
        '  "email": "email address if present in the resume, or empty string",\n'
        '  "target_titles": "2-4 comma-separated job titles this candidate '
        'would REALISTICALLY TARGET next. Rules: (1) include seniority prefix '
        '(Junior / Mid / Senior / Staff / Principal / Director / VP) based on '
        "their years and scope of experience; (2) reference specific tech "
        "stacks, tools, or specializations from the resume — not bare labels. "
        'GOOD: \'Senior Python Developer, Backend Engineer, Platform Engineer\'. '
        'BAD: \'Software Engineer, Developer\'.",\n'
        '  "preferred_locations": "comma-separated locations mentioned in the '
        'resume, or \'Remote\' if the candidate seems open to remote work",\n'
        '  "min_salary": "integer USD estimate of a realistic minimum annual '
        'base salary. Use these rough anchors: junior 60000-80000, mid-level '
        '80000-120000, senior 120000-170000, staff/principal 170000-250000, '
        'director+ 200000+. Adjust up for tech/finance/FAANG signals, down for '
        'non-profit/government/early-career. The number should almost always '
        'land between 60000 and 250000. Only return 0 if the resume is empty, '
        'garbled, or contains zero professional signal. Return as a bare '
        'integer, not a string or formatted number.",\n'
        '  "looking_for": "2-3 sentence summary, written in third person, of '
        'the kind of role this candidate would realistically seek based on '
        'their background and trajectory"\n'
        "}\n\n"
        "Do not invent specific companies, titles, or salary figures unsupported "
        "by the resume. But do infer reasonably — a resume showing 8 years of "
        "Python and AWS experience clearly justifies 'Senior Python Developer' "
        "and a six-figure salary, even if those exact words aren't written.\n\n"
        f"RESUME:\n{resume_text[:4000]}"
    )

    try:
        text = _call_llm(prompt)
        data = json.loads(_clean_json_response(text))
    except QuotaExhausted:
        return {}
    except Exception as e:
        print(f"[grader] parse_resume_to_profile failed: {str(e)[:140]}")
        return {}

    if not isinstance(data, dict):
        return {}

    # Sanitize — never let a bad LLM string crash the form's number input
    out = {}
    for k in ("full_name", "email", "target_titles", "preferred_locations", "looking_for"):
        v = data.get(k)
        out[k] = v.strip() if isinstance(v, str) else ""
    out["min_salary"] = _sanitize_salary(data.get("min_salary", 0))
    return out


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
        text = _call_llm(prompt)
        return text.strip()
    except QuotaExhausted:
        return ""
    except Exception as e:
        print(f"[grader] Resume summary failed: {str(e)[:140]}")
        return ""


# -- Single Job Grading ------------------------------------------------------

def _build_grade_prompt(job: dict, profile: dict) -> str:
    """Build the rich-scoring prompt for a single job.

    Returns a structured match analysis that feels personal — the narrative
    references specific things from the candidate's resume to come off as
    hand-picked, not algorithmic.
    """
    name = profile.get("full_name", "the candidate")
    first_name = name.split()[0] if name and name.strip() else "the candidate"
    titles = profile.get("target_titles", "")
    locations = profile.get("preferred_locations", "")
    industries = profile.get("preferred_industries", "")
    target_companies = profile.get("target_companies", "")
    salary = profile.get("min_salary", 0)
    target_ote = profile.get("target_ote", 0) or 0
    looking_for = profile.get("looking_for", "")
    dealbreakers = profile.get("dealbreakers", "")
    resume_summary = profile.get("resume_summary", "")
    ote_line = f"\n- Target total compensation (OTE): ${target_ote:,}" if target_ote else ""
    companies_line = f"\n- Companies of high interest: {target_companies}" if target_companies else ""
    resumes_section, resume_schema_line = _resumes_block(profile, resume_summary)

    return f"""You are an expert job-matching advisor writing a personalized \
assessment for {first_name}. Grade this job against the candidate profile and \
return ONLY valid JSON, no markdown fences:

{{
  "match_score": integer 0-100 overall fit (see scoring guide below),
  "match_reasons": ["2 to 3 specific reasons this role fits THIS candidate. \
Each reason MUST reference a concrete detail from their resume — a company \
name, tool, industry, or years of experience (e.g. 'Requires enterprise \
territory management — matches your 7 years at Rentokil'). NOT generic \
('you have relevant experience')."],
  "caution_flags": ["0 to 2 honest concerns. Examples: 'base salary may be \
below your $120k floor', 'startup with no public funding info', 'requires \
on-site work in a location you did not list'. Use an empty list [] if none."],
  "role_summary": "one plain-English sentence describing what the role \
actually involves day-to-day (not just the job title)",
  "narrative": "2-3 sentences written TO the candidate in second person \
('This role aligns with your 8 years at Acme managing enterprise \
accounts...'). MUST reference specific tools, companies, or roles from their \
resume to feel hand-picked. Highlight the most exciting aspect for someone \
with their background.",
{resume_schema_line}}}

SCORING GUIDE:
- 90-100: rare exceptional fit; strong match on role, domain, tools, seniority, and compensation signals
- 75-89: strong fit; clear alignment on most dimensions
- 50-74: reasonable fit; some alignment but notable gaps
- 25-49: weak fit; limited overlap with background or preferences
- 0-24: poor fit; major mismatches

RULES:
- If any dealbreaker is clearly violated, cap match_score at 25 and name the violated dealbreaker in caution_flags.
- If base salary appears to be less than 50% of total comp (commission trap), add that to caution_flags.
- Never invent specifics from the resume that aren't there — if you don't have enough resume detail, say so in a caution_flag and keep the narrative shorter/more generic.

CANDIDATE PROFILE:
- Name: {name}
- Targeting roles: {titles}
- Preferred locations: {locations}
- Preferred industries: {industries}{companies_line}
- Minimum base salary: ${salary:,}{ote_line}
- What they want: {looking_for}
- Dealbreakers: {dealbreakers}
{resumes_section}

JOB LISTING:
- Title: {job.get('title', '')}
- Company: {job.get('company', '')}
- Location: {job.get('location', '')}
- Source: {job.get('source', '')}
- Description: {job.get('description', '')}"""


# Minimum match_score to route a job to the "approved" list (vs graveyard).
# 50 is looser than the old rating-3-of-5 threshold — user preference.
APPROVAL_THRESHOLD = 50


# Fallback grade dicts — returned when LLM can't respond (quota, error, no key).
# Shape matches what the LLM returns on success so display code can treat every
# job["grade"] uniformly.
RATE_LIMITED_GRADE = {
    "match_score": 0,
    "match_reasons": [],
    "caution_flags": ["AI grader is temporarily rate-limited. Try again in a few minutes."],
    "role_summary": "",
    "narrative": "",
    "recommended_action": "Skip",
    "recommended_resume": "",
}
FAILED_GRADE = {
    "match_score": 0,
    "match_reasons": [],
    "caution_flags": ["AI grader couldn't assess this role (parse error)."],
    "role_summary": "",
    "narrative": "",
    "recommended_action": "Skip",
    "recommended_resume": "",
}
UNCONFIGURED_GRADE = {
    "match_score": 0,
    "match_reasons": [],
    "caution_flags": ["AI grader not configured (missing GEMINI_API_KEY)."],
    "role_summary": "",
    "narrative": "",
    "recommended_action": "Skip",
    "recommended_resume": "",
}


def _resumes_block(profile: dict, fallback_summary: str) -> tuple:
    """Build the resume context to inject into the grading prompt.

    Returns (resumes_section_text, schema_instruction_text):
      - For users with > 1 resume: enumerates each {label, summary} so the LLM
        can pick the best-fit version per job; the schema instruction requires
        recommended_resume to be set.
      - For single-resume users: same single 'Resume summary: ...' line we've
        always sent; schema instruction tells the LLM to leave recommended_resume
        as an empty string. No extra tokens vs pre-multi-resume era.
    """
    resumes = profile.get("resumes") or []
    if not isinstance(resumes, list):
        resumes = []
    # Filter out blank entries so labels with no text don't pollute the prompt
    resumes = [
        r for r in resumes
        if isinstance(r, dict) and (r.get("text") or r.get("summary"))
    ]
    if len(resumes) > 1:
        lines = ["RESUMES AVAILABLE (pick the best-fit version for this job):"]
        for r in resumes:
            label = (r.get("label") or "Untitled").strip() or "Untitled"
            summary = (r.get("summary") or "").strip() or "(no summary available)"
            lines.append(f'  - "{label}": {summary}')
        section = "\n".join(lines)
        schema = (
            '  "recommended_resume": "the LABEL (verbatim) of the best-fit '
            'resume from the list above. Required when multiple resumes are listed.",\n'
        )
        return section, schema
    # Single-resume / no-resume case: keep legacy single-line format
    section = f"Resume summary: {fallback_summary}"
    schema = (
        '  "recommended_resume": "leave as empty string \\"\\" — the candidate '
        'has only one resume, so no recommendation is needed.",\n'
    )
    return section, schema


def _derive_recommended_action(grade: dict, threshold: int) -> str:
    """Convert a numeric grade into an actionable label.

    - Apply: score >= 80 AND no more than one caution. Strong fit; no major reservations.
    - Skip:  score < threshold. Below the user's selectivity floor.
    - Maybe: everything in between. Worth a look but not a slam dunk.
    """
    score = int(grade.get("match_score", 0) or 0)
    cautions = grade.get("caution_flags", []) or []
    if score < threshold:
        return "Skip"
    if score >= 80 and len(cautions) <= 1:
        return "Apply"
    return "Maybe"


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
        text = _call_llm(prompt)
        return json.loads(_clean_json_response(text))
    except QuotaExhausted:
        return dict(RATE_LIMITED_GRADE)
    except Exception as e:
        print(f"[grader] grade_single failed: {str(e)[:140]}")
        return dict(FAILED_GRADE)


# -- Batch Grading -----------------------------------------------------------

def _build_batch_prompt(jobs_batch: list, profile: dict) -> str:
    """Build a rich-scoring prompt that grades multiple jobs in one LLM call."""
    name = profile.get("full_name", "the candidate")
    first_name = name.split()[0] if name and name.strip() else "the candidate"
    titles = profile.get("target_titles", "")
    locations = profile.get("preferred_locations", "")
    industries = profile.get("preferred_industries", "")
    target_companies = profile.get("target_companies", "")
    salary = profile.get("min_salary", 0)
    target_ote = profile.get("target_ote", 0) or 0
    looking_for = profile.get("looking_for", "")
    dealbreakers = profile.get("dealbreakers", "")
    resume_summary = profile.get("resume_summary", "")
    ote_line = f"\n- Target total compensation (OTE): ${target_ote:,}" if target_ote else ""
    companies_line = f"\n- Companies of high interest: {target_companies}" if target_companies else ""
    resumes_section, resume_schema_line = _resumes_block(profile, resume_summary)

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

    return f"""You are an expert job-matching advisor writing personalized \
assessments for {first_name}. Grade these {len(jobs_batch)} jobs and return \
ONLY a valid JSON array (no markdown fences), one object per job in the same \
order they appear below. Each object must have exactly these keys:

{{
  "match_score": integer 0-100 overall fit,
  "match_reasons": ["2-3 specific reasons this fits THIS candidate, each \
referencing a concrete detail from their resume (company, tool, years, \
industry) — NOT generic phrasing"],
  "caution_flags": ["0-2 honest concerns. Empty list [] if none."],
  "role_summary": "one sentence describing what the role actually involves",
  "narrative": "2-3 sentences written TO the candidate in second person \
('This role aligns with your...'). MUST reference specific resume details \
(tools, companies, roles) to feel hand-picked.",
{resume_schema_line}}}

SCORING GUIDE:
- 90-100: rare exceptional fit
- 75-89: strong fit on most dimensions
- 50-74: reasonable fit with notable gaps
- 25-49: weak fit
- 0-24: poor fit

RULES:
- If any dealbreaker is clearly violated, cap match_score at 25 and name the violated dealbreaker in caution_flags.
- If base salary appears less than 50% of total comp (commission trap), add that to caution_flags.
- Don't invent resume specifics. If you lack resume detail, keep the narrative generic and note the missing info in a caution_flag.

CANDIDATE PROFILE:
- Name: {name}
- Targeting roles: {titles}
- Preferred locations: {locations}
- Preferred industries: {industries}{companies_line}
- Minimum base salary: ${salary:,}{ote_line}
- What they want: {looking_for}
- Dealbreakers: {dealbreakers}
{resumes_section}
{jobs_text}"""


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
        text = _call_llm(prompt)
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
    global _quota_dead, _gemini_dead, _anthropic_dead, _ollama_dead, _ollama_alive_checked
    # Reset all per-provider kill switches per invocation — any of them may
    # have recovered between runs (Gemini quota tick, Anthropic rate window,
    # Ollama service restart). The Ollama alive-check cache also resets.
    _quota_dead = False
    _gemini_dead = False
    _anthropic_dead = False
    _ollama_dead = False
    _ollama_alive_checked = False

    # Per-profile threshold (set by user via match-selectivity slider).
    # Falls back to the module default if missing or invalid.
    threshold = profile.get("match_threshold")
    if not isinstance(threshold, int) or threshold < 0 or threshold > 100:
        threshold = APPROVAL_THRESHOLD

    approved = []
    graveyard = []
    total = len(jobs)

    for i in range(0, total, BATCH_SIZE):
        batch = jobs[i:i + BATCH_SIZE]
        grades = grade_batch(batch, profile)

        for job, grade in zip(batch, grades):
            # Derive Apply/Maybe/Skip from the numeric score + cautions
            grade["recommended_action"] = _derive_recommended_action(grade, threshold)
            job["grade"] = grade
            score = grade.get("match_score", 0)

            # caution_flags are informational only — they don't gate approval
            if score < threshold:
                graveyard.append(job)
            else:
                approved.append(job)

        if on_progress:
            on_progress(min(i + BATCH_SIZE, total), total)

        # If ALL providers are dead mid-loop, mark remaining jobs as
        # rate-limited and stop. (_call_llm only raises QuotaExhausted when
        # every provider has tripped, so this means we have no more options.)
        all_dead = _gemini_dead and _anthropic_dead and _ollama_dead
        if all_dead and i + BATCH_SIZE < total:
            for remaining in jobs[i + BATCH_SIZE:]:
                _stub = dict(RATE_LIMITED_GRADE)
                _stub["recommended_action"] = "Skip"
                remaining["grade"] = _stub
                graveyard.append(remaining)
            break

        # Rate limit delay between batches
        if i + BATCH_SIZE < total:
            time.sleep(GRADE_DELAY)

    # Sort approved: highest match_score first
    approved.sort(key=lambda j: j["grade"].get("match_score", 0), reverse=True)

    # quota_exhausted in the return tuple now means "all providers dead",
    # not just Gemini. _quota_dead alias mirrors the Gemini status for any
    # legacy reader.
    all_dead = _gemini_dead and _anthropic_dead and _ollama_dead
    return approved, graveyard, all_dead
