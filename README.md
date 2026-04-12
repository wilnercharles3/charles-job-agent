# Charles Job Agent

### Project Overview
The Charles Job Agent is a dual-component AI system designed to automate the job search process in a seemless two step process. It combines a simple web app with an smart background agent that does all the heavy lifting ensure high-quality job matches are identified and delivered daily.

### How It Works
The system have two main jobs


#1. **The Web Dashboard (app.py):** A simple and brief input form where the user can upload their resumes, define their ideal roles, and instantly search for matches.
#2. **The Autonomous Agent (autopilot.py):** the AI bot in the background that runs every morning at 5:00 AM EST. It scans multiple job boards, grades opportunities using AI, and emails the best matches directly to the user.

### Core Features
* **Multi-Source Aggregation:** The agent pulls live data from five major sources, including Adzuna, The Muse, RemoteOK, JSearch, and Google Jobs.
* **AI-Powered Grading:** Every job is analyzed by Google Gemini 2.0. Roles are graded on a scale of 1 to 5 and categorized as Strategic, Professional, or Skip based on the user's specific resume and goals.
* **Automatic Filter for Quality:** The agent is programmed to identify and flag "commission traps" or low-quality listings where the base salary does not meet professional standards.
* **The Graveyard:** A specialized section in the UI that shows rejected jobs along with the AI's reasoning, providing transparency into why certain roles were skipped.

### Technical Stack
* **Frontend:** Streamlit
* **Database:** Supabase (PostgreSQL)
* **Intelligence:** Google Gemini 2.0 Flash
* **Automation:** GitHub Actions
* **Communication:** Gmail SMTP

---
*Developed by Wilner Charles — Python Developer at the University of Baltimore.*
