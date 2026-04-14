# AI Reference Guide — charles-job-agent

> **Purpose:** This document is a reference for AI assistants (Claude, Gemini, Copilot, etc.) working on this repo. Read this FIRST before making changes.

---

## Architecture Overview

This is a **cloud-only** job matching agent. There is no local setup required. It runs on:

- **Streamlit Cloud** — hosts the user-facing web app (`app.py`)
- **GitHub Actions** — runs the daily automated scan (`autopilot.py` via `daily_scan.yml`)
- **Supabase** — stores user profiles and sent job tracking
- **Gemini AI** — grades jobs and summarizes resumes

### File Map

| File | Purpose | Touch carefully? |
|------|---------|-----------------|
| `app.py` | Streamlit UI: profile form + instant scan | YES |
| `autopilot.py` | Daily cron job: fetch, grade, email top matches | YES |
| `jobs.py` | Shared job fetchers (5 APIs), dedup, pre-filter | Moderate |
| `grader.py` | Shared Gemini AI: resume summary + job grading | Moderate |
| `db.py` | Shared Supabase client: profiles + sent_jobs | Moderate |
| `daily_scan.yml` | GitHub Actions workflow (cron + manual trigger) | YES |
| `requirements.txt` | Python deps for cloud deploy | Low risk |
| `supabase_setup.sql` | Database schema reference | Read-only |

---

## UX Flow (app.py)

1. User opens Streamlit app
2. Fills out profile form: name, email, resume, job preferences
3. Clicks **"Save My Profile"**
4. Resume is summarized by Gemini AI in the background
5. Profile + summary saved to Supabase
6. **"Instant Job Scan"** button appears (ONLY after successful save)
7. User clicks scan -> fetches from 5 job boards, grades with AI, shows results

**The Instant Scan button must NEVER appear before the profile is saved.**

---

## Function Signatures (CRITICAL — do not break these)

### jobs.py

```python
fetch_all_jobs(titles: list, locations: list) -> list[dict]
# Each dict has: title, company, location, description, url, source

pre_filter(jobs: list, titles: list) -> list[dict]

deduplicate(jobs: list) -> list[dict]
```

### grader.py

```python
summarize_resume(resume_text: str) -> str

grade_single(job: dict, profile: dict) -> dict
# Returns: {rating, label, reason, commission_trap}

grade_all_jobs(jobs: list, profile: dict, on_progress=None) -> tuple[list, list]
# Returns: (approved_jobs, graveyard_jobs)
# Profile dict keys: full_name, target_titles, preferred_locations,
#   min_salary, looking_for, dealbreakers, resume_summary
```

### db.py

```python
save_profile(user_data: dict)
load_profile(email: str) -> dict
list_profiles() -> list[dict]
```

---

## Key Mappings (app.py <-> grader.py)

The profile form saves data with these keys to Supabase:
`name, email, target_titles, location_pref, min_salary, job_type, looking_for, dealbreakers, resume_summary`

The grader expects these keys:
`full_name, target_titles, preferred_locations, min_salary, looking_for, dealbreakers, resume_summary`

**app.py must map between these when calling grade_all_jobs.** See the `profile_for_grader` dict in app.py.

---

## Automation (autopilot.py + daily_scan.yml)

- Runs daily at **10:00 UTC (5:00 AM EST)** via GitHub Actions cron
- Also has `workflow_dispatch` for manual triggers
- Workflow: checkout -> setup Python 3.11 -> install deps -> run `autopilot.py`
- autopilot.py loads ALL profiles from Supabase, fetches jobs, grades them, emails top matches
- **DO NOT modify the cron schedule or the workflow without explicit permission**

### Required GitHub Secrets

`SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `RAPIDAPI_KEY`, `SERPAPI_KEY`

---

## Checklist Before Committing Changes

- [ ] **Does app.py still have the profile form?** (name, email, resume upload, preferences)
- [ ] **Does the form still save to Supabase via db.save_profile()?**
- [ ] **Does resume summarization still call grader.summarize_resume()?**
- [ ] **Does the Instant Scan button only appear AFTER successful profile save?**
- [ ] **Does Instant Scan use fetch_all_jobs() with list args, not strings?**
- [ ] **Does Instant Scan pass the correct profile dict to grade_all_jobs()?**
- [ ] **Is autopilot.py untouched?** (unless explicitly asked to change it)
- [ ] **Is daily_scan.yml untouched?** (unless explicitly asked to change it)
- [ ] **Does requirements.txt include all needed packages?**
- [ ] **No hardcoded API keys anywhere?** (all from env vars / secrets)

---

## Common Mistakes (Things That Broke Before)

1. **Replacing the entire profile form with just a scan button** — This breaks the app because there is no way to set user data without the form. The scan depends on saved profile data.

2. **Using wrong function signatures** — `fetch_all_jobs()` takes `(titles: list, locations: list)`, NOT a single string. You must split comma-separated user input into lists.

3. **Mismatched profile dict keys** — `grader.py` expects `full_name` and `preferred_locations`, but `db.py` stores `name` and `location_pref`. Always map between them.

4. **Breaking indentation** — Python is indent-sensitive. If using GitHub web editor, be careful with auto-indent. Use `document.execCommand('insertText')` via JS to bypass auto-indent when pasting.

5. **Adding features that require local environment** — This app runs entirely in the cloud (Streamlit Cloud + GitHub Actions). Do not add features that require local file system access, local cron jobs, or local databases.

---

## Adding New Features (Guidelines)

- **New job boards**: Add a new `fetch_xxx()` function in `jobs.py`, add it to `fetch_all_jobs()`
- **New profile fields**: Add to the form in `app.py`, update `supabase_setup.sql`, update `db.py`
- **New grading criteria**: Modify the prompt templates in `grader.py`
- **New UI sections**: Add them BELOW the existing form in `app.py`, never replace the form

---

*Last updated: April 2026*
