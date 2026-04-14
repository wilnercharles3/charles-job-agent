# AI_REFERENCE.md - Context for AI assistants working on this project

## Project Overview
Job Match Agent - A production Streamlit web app that searches 5 job boards,
grades listings with Google Gemini AI, and emails daily job matches to users.

**Live URL:** https://charles-job-agent-9cpadgvzhra8g38wsrjecd.streamlit.app/
**Repo:** https://github.com/wilnercharles3/charles-job-agent

## Architecture
- **Frontend:** Streamlit (app.py) - hosted on Streamlit Cloud
- **Database:** Supabase (PostgreSQL) - stores user profiles and sent-job history
- **AI Grading:** Google Gemini 2.0 Flash (grader.py) - grades jobs 1-5 stars
- **Email:** Gmail SMTP with App Password (welcome_email.py, autopilot.py)
- **Job Sources:** Adzuna, The Muse, RemoteOK, JSearch (RapidAPI), Google Jobs (SerpAPI)

## Key Files
| File | Purpose |
|------|---------|
| app.py | Streamlit UI - profile form + instant job scan |
| jobs.py | Job fetchers for 5 boards + pre_filter + deduplicate |
| grader.py | Gemini AI grading + resume summarization |
| db.py | Supabase CRUD - save/load profiles, track sent jobs |
| welcome_email.py | HTML welcome email sent after profile save |
| autopilot.py | Daily scan script - fetch, grade, email top matches |
| daily_scan.yml | GitHub Actions workflow for daily autopilot runs |
| requirements.txt | Python dependencies |

## Environment Variables (Streamlit Secrets)
All secrets stored in Streamlit Cloud Settings > Secrets (TOML format):
- SUPABASE_URL, SUPABASE_KEY - Supabase connection
- GEMINI_API_KEY - Google Gemini AI
- ADZUNA_APP_ID, ADZUNA_APP_KEY - Adzuna job board
- RAPIDAPI_KEY - JSearch via RapidAPI
- SERPAPI_KEY - Google Jobs via SerpAPI
- GMAIL_USER, GMAIL_APP_PASSWORD - Gmail SMTP for emails

Code uses os.getenv() which Streamlit Cloud populates from top-level secrets.

## Critical Rules
- DO NOT remove the profile form or the Supabase save logic
- DO NOT hardcode values in form fields - use placeholders only
- Resume section must have BOTH file upload AND paste text area options
- Salary default must be 0 (not pre-filled)
- Missing API keys should be handled gracefully (skip that source, don't crash)
- welcome_email.py accepts user_data dict parameter (not no-args)
- app.py calls send_welcome_email(user_data) after profile save

## Function Signatures
- `jobs.fetch_all_jobs(titles: list, locations: list) -> list[dict]`
- `jobs.pre_filter(jobs: list, titles: list) -> list[dict]`
- `grader.grade_all_jobs(jobs, profile, on_progress=None) -> (approved, graveyard)`
- `grader.summarize_resume(text: str) -> str`
- `db.save_profile(data: dict) -> bool`
- `db.load_profile(email: str) -> dict`
- `db.load_all_profiles() -> list`
- `welcome_email.send_welcome_email(user_data: dict) -> bool`

## Job Dict Schema
Each job returned by fetchers has these keys:
```python
{"title": str, "company": str, "location": str, "description": str, "url": str, "source": str}
```

## Remote Job Handling
- When location is "Remote"/"anywhere"/"wfh", fetchers skip location param
- Adzuna: searches US-wide by title only (no where param)
- The Muse: maps titles to predefined API categories
- RemoteOK: matches individual keywords from titles
- JSearch: appends "remote" to query
- SerpAPI: appends "remote jobs" to query

## GitHub Editor Warning
When editing Python files via GitHub web editor, the CodeMirror 6 editor
can mangle indentation. Always use the CodeMirror dispatch API:
```javascript
const view = document.querySelector('.cm-content').cmTile.view;
view.dispatch({changes: {from: 0, to: view.state.doc.length, insert: newContent}});
```
Never use the type tool for multi-line Python code in the GitHub editor.

## Status (Updated 2026-04-14)
- App is LIVE and working on Streamlit Cloud
- Profile save + Supabase integration: WORKING
- Welcome email: WORKING (sends HTML email via Gmail SMTP)
- Job fetching from 5 boards: WORKING (105 raw jobs in test)
- Pre-filtering: WORKING (105 -> 15 relevant)
- AI grading with Gemini: WORKING (some grading failures due to API limits)
- Daily autopilot emails: configured via GitHub Actions (daily_scan.yml)
