# Charles Job Agent

An AI-powered job matching system that scans five major job boards every day, grades each listing against your profile using Google Gemini, and emails you only the roles worth applying to.

Built for real people looking for work — not developers. Your friends fill out a simple form, and the agent handles everything else.

---

## How It Works

**Step 1 — Fill out your profile**

Visit the Streamlit web app (`app.py`). Enter your name, email, resume, target job titles, locations, salary floor, and a free-text description of what you want. Save once and you are done.

**Step 2 — Get daily matches by email**

Every morning, `autopilot.py` runs via GitHub Actions. It pulls listings from Adzuna, The Muse, RemoteOK, JSearch (RapidAPI), and Google Jobs (SerpAPI). Each job is graded by Gemini against your resume and preferences. Only the top-rated matches land in your inbox as a clean HTML email with star ratings and one-click apply links.

Want to update your preferences? Come back to the form anytime using your bookmarked link.

---

## Architecture

```
User → app.py (Streamlit form) → Supabase (profiles table)
                                        ↓
              GitHub Actions cron → autopilot.py
                                        ↓
                          jobs.py (5 job board APIs)
                                        ↓
                        grader.py (Gemini AI grading)
                                        ↓
                          Email (Gmail SMTP) → User
```

| File | Purpose |
|---|---|
| `app.py` | Streamlit intake form — collects user profile, saves to Supabase, summarizes resume with AI |
| `autopilot.py` | Headless daily scanner — fetches jobs, grades with AI, emails results |
| `db.py` | Shared Supabase client — profile CRUD, sent-jobs tracking |
| `jobs.py` | Job fetchers for all 5 sources, deduplication, pre-filtering |
| `grader.py` | Gemini AI grading (batched), resume summarization, descriptive match labels |
| `supabase_setup.sql` | Database schema for profiles and sent_jobs tables |

---

## Tech Stack

- **Frontend**: Streamlit
- **Database**: Supabase (PostgreSQL)
- **AI**: Google Gemini 2.0 Flash
- **Automation**: GitHub Actions (daily cron)
- **Email**: Gmail SMTP
- **Job Sources**: Adzuna, The Muse, RemoteOK, JSearch, Google Jobs

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/wilnercharles3/charles-job-agent.git
cd charles-job-agent
pip install -r requirements.txt
```

### 2. Create a Supabase project

- Go to [supabase.com](https://supabase.com) and create a free project.
- Open the SQL Editor and run `supabase_setup.sql` to create the `profiles` and `sent_jobs` tables.

### 3. Set environment variables

Copy `.env.example` to `.env` and fill in your keys:

```
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
GEMINI_API_KEY=your_gemini_api_key
GMAIL_USER=your_gmail_address
GMAIL_APP_PASSWORD=your_gmail_app_password
ADZUNA_APP_ID=your_adzuna_app_id
ADZUNA_APP_KEY=your_adzuna_app_key
RAPIDAPI_KEY=your_rapidapi_key
SERPAPI_KEY=your_serpapi_key
```

**Notes on API keys:**
- `GEMINI_API_KEY`: Free at [aistudio.google.com](https://aistudio.google.com)
- `GMAIL_APP_PASSWORD`: Generate an App Password in your Google Account security settings (requires 2FA)
- `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`: Free at [developer.adzuna.com](https://developer.adzuna.com)
- `RAPIDAPI_KEY`: Sign up at [rapidapi.com](https://rapidapi.com) and subscribe to JSearch
- `SERPAPI_KEY`: Free tier at [serpapi.com](https://serpapi.com)
- Missing API keys are handled gracefully — the agent skips any source without valid credentials.

### 4. For GitHub Actions (daily automation)

Add each environment variable as a **Repository Secret** under Settings > Secrets and variables > Actions.

The included `.github/workflows/daily_scan.yml` runs `autopilot.py` every morning at 5:00 AM EST.

### 5. Run the web app locally

```bash
streamlit run app.py
```

### 6. Run the daily scanner manually

```bash
python autopilot.py
```

---

## AI Grading

Each job is graded by Gemini against the user's resume summary, target titles, salary floor, location preferences, free-text goals, and dealbreakers.

Jobs are batched 3-5 at a time to reduce API calls. Each graded job receives:

- **Rating**: 1–5 stars
- **Label**: `STRATEGIC` (perfect fit), `PROFESSIONAL` (solid option), or `SKIP`
- **Reason**: A sentence explaining why — descriptive and enthusiastic for high matches, honest for medium ones, brief for skips
- **Commission trap detection**: Flags roles where base salary is likely below 50% of total comp

Only jobs scoring 3+ stars are emailed. Jobs already sent are tracked in `sent_jobs` to prevent duplicates.

---

## Returning Users

After saving their profile, users get a bookmark link like:

```
https://your-app.streamlit.app/?email=friend@email.com
```

Visiting that link loads their existing profile so they can update their resume, preferences, or dealbreakers anytime.

---

## Developed by

Wilner Charles — Python Developer, University of Baltimore
