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
| app.py | Streamlit UI - profile form + instant job scan with detailed results |
| jobs.py | Job fetchers for 5 boards + validate + pre_filter + deduplicate |
| grader.py | Gemini AI grading + resume summarization |
| db.py | Supabase CRUD - save/load profiles, track sent jobs |
| welcome_email.py | HTML welcome email with site link, sent after profile save |
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
- All jobs must have valid URLs (http/https) and real company names
- Spam/training-program companies are filtered out in jobs.py

## Function Signatures
- `jobs.fetch_all_jobs(titles, locations) -> list[dict]` (includes validation)
- `jobs.validate_jobs(jobs) -> list[dict]` (URL + spam filtering)
- `jobs.pre_filter(jobs, titles) -> list[dict]`
- `grader.grade_all_jobs(jobs, profile, on_progress=None) -> (approved, graveyard)`
- `grader.summarize_resume(text) -> str`
- `db.save_profile(data) -> bool`
- `db.load_profile(email) -> dict`
- `welcome_email.send_welcome_email(user_data) -> bool`

## Job Dict Schema
Each job returned by fetchers has these keys:
```python
{"title": str, "company": str, "location": str, "description": str, "url": str, "source": str}
```

## Job Result Display (app.py)
Each approved job shows:
- Company, Location, Source in a two-column layout
- Apply/View Job link (clickable, opens source site)
- AI Assessment with detailed reasoning
- Commission trap warning if detected
- Description preview snippet (first ~300 chars)
- "Open full listing on [source]" link at bottom

Skipped/low-rated jobs show title, company, source, rating, reason, and a View link.

## Job Validation Pipeline (jobs.py)
1. fetch_all_jobs() collects from 5 boards
2. deduplicate() removes exact title+company dupes
3. validate_jobs() filters:
   - Jobs without valid URLs (must start with http, min 15 chars)
   - Known spam companies (Revature, Smoothstack, SynergisticIT, etc.)
   - Spam title patterns (unpaid, volunteer, training program)
   - Jobs missing title or company name
4. pre_filter() keyword-matches against user's target titles

## Welcome Email (welcome_email.py)
- Includes APP_URL constant linking to the Streamlit app
- Big blue "Open Job Match Agent" CTA button in email body
- Footer with clickable link to the app
- Shows user's current settings (titles, location, salary)
- Example job matches section
- Tips for best results

## Remote Job Handling
- When location is "Remote"/"anywhere"/"wfh", fetchers skip location param
- Adzuna: searches US-wide by title only
- The Muse: maps titles to predefined API categories
- RemoteOK: matches individual keywords from titles
- JSearch: appends "remote" to query
- SerpAPI: appends "remote jobs" to query

## GitHub Editor Warning
When editing Python files via GitHub web editor, use CodeMirror dispatch API:
```javascript
const view = document.querySelector('.cm-content').cmTile.view;
view.dispatch({changes: {from: 0, to: view.state.doc.length, insert: newContent}});
```
Never use the type tool for multi-line Python in the GitHub editor.

## Status (Updated 2026-04-14)
- App is LIVE on Streamlit Cloud
- Profile save + Supabase: WORKING
- Welcome email with site link: WORKING
- Job fetching from 5 boards: WORKING (105 raw jobs in test)
- URL validation + spam filtering: ACTIVE
- Pre-filtering: WORKING
- AI grading with detailed results: WORKING
- Job display with source links + description previews: ACTIVE
- Daily autopilot emails: configured via GitHub Actions
