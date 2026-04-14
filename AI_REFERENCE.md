# AI_REFERENCE.md - Project Reference for AI Assistants

## Project: Job Match Agent
**Repo:** https://github.com/wilnercharles3/charles-job-agent  
**Live App:** https://charles-job-agent-9cpadgvzhra8g38wsrjecd.streamlit.app/  
**Last Updated:** April 14, 2026

## Architecture Overview
- **app.py** - Streamlit Cloud UI. Profile form, resume upload/paste, Supabase save, welcome email, instant job scan.
- **autopilot.py** - Headless daily scanner. Runs via GitHub Actions at 5 AM EST. Fetches jobs, grades with AI, emails results.
- **jobs.py** - Job fetchers for 5 boards (Adzuna, The Muse, RemoteOK, JSearch, Google Jobs). Includes deduplication, URL validation, spam filtering.
- **grader.py** - Gemini AI grading. Resume summarization, batch grading (3 jobs per API call), 1-5 star rating system.
- **db.py** - Supabase client. Profile CRUD, sent-jobs tracking, dedup filtering.
- **welcome_email.py** - HTML welcome email with app link button, tips, example job list, user settings summary.

## Critical Rules
- DO NOT remove the profile form or the Supabase save logic.
- Missing API keys should be handled gracefully (skip that source, don't crash).
- When editing Python files via GitHub web editor, ALWAYS use CodeMirror dispatch API:
  ```javascript
  const view = document.querySelector('.cm-content').cmTile.view;
  view.dispatch({changes: {from: 0, to: view.state.doc.length, insert: newContent}});
  ```
- Never use the type tool for multi-line Python code - it produces broken indentation.

## Field Name Mapping (IMPORTANT)
app.py saves profiles with these keys:
- name, email, target_titles, location_pref, min_salary, job_type, looking_for, dealbreakers, resume_summary

autopilot.py/grader.py expect:
- full_name, target_titles, preferred_locations, min_salary, etc.

autopilot.py has a `normalise_profile()` function that maps between these conventions.

## Daily Autopilot Pipeline
1. GitHub Actions runs daily_scan.yml at 10:00 UTC (5:00 AM EST)
2. autopilot.py loads ALL profiles from Supabase
3. For each profile: normalise fields -> fetch jobs -> pre-filter -> filter already-sent -> grade with AI -> email approved (3+ stars)
4. Sent jobs are tracked in Supabase `sent_jobs` table to avoid duplicates

## Secrets Configuration
**Streamlit Cloud** (TOML format in app settings):
- SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY, GMAIL_USER, GMAIL_APP_PASSWORD
- ADZUNA_APP_ID, ADZUNA_APP_KEY, RAPIDAPI_KEY, SERPAPI_KEY

**GitHub Actions** (Repository secrets - all 9 configured April 12, 2026):
- Same 9 keys as above, set in Settings > Secrets and variables > Actions

## Current Status (April 14, 2026)
- App is LIVE and working on Streamlit Cloud
- Profile save to Supabase: WORKING
- Welcome email with app link: WORKING
- Instant job scan: WORKING (fetches ~97 validated jobs, filters to ~15, grades with AI)
- Daily autopilot: RUNNING (3 successful scheduled runs so far)
- Note: autopilot found 0 profiles on runs #2-#4 because profile was freshly saved today. Tomorrow's run should pick it up.
- URL validation + spam filtering: WORKING
- Enhanced job display with company/location/source, apply links, AI assessment, description previews: WORKING

## Known Issues
- Gemini API rate limiting can slow the last batch of grading during instant scan
- autopilot previously had field name mismatch (name vs full_name, location_pref vs preferred_locations) - FIXED with normalise_profile()
- GitHub web editor mangles Python indentation - FIXED by always using CodeMirror dispatch API

## Supabase Tables
- **profiles** - User profiles (email is primary key for upsert)
- **sent_jobs** - Tracks which jobs have been emailed to which user (prevents duplicates)
