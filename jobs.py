"""
jobs.py - Job fetchers, pre-filtering, and deduplication.

Shared module used by both app.py and autopilot.py.
Each fetcher returns a list of dicts with keys:
    title, company, location, description, url, source
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

TIMEOUT = 15


def fetch_adzuna(titles: list, locations: list) -> list:
    jobs = []
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("[jobs] Adzuna keys missing, skipping.")
        return jobs
    for title in titles:
        for loc in locations:
            try:
                r = requests.get(
                    "https://api.adzuna.com/v1/api/jobs/us/search/1",
                    params={
                        "app_id": ADZUNA_APP_ID,
                        "app_key": ADZUNA_APP_KEY,
                        "results_per_page": 10,
                        "what": title,
                        "where": loc,
                        "content-type": "application/json",
                    },
                    timeout=TIMEOUT,
                )
                if r.status_code == 200:
                    for j in r.json().get("results", []):
                        jobs.append({
                            "title": j.get("title", ""),
                            "company": j.get("company", {}).get("display_name", ""),
                            "location": j.get("location", {}).get("display_name", ""),
                            "description": j.get("description", "")[:800],
                            "url": j.get("redirect_url", ""),
                            "source": "Adzuna",
                        })
            except Exception as e:
                print(f"[jobs] Adzuna error ({title}, {loc}): {e}")
    return jobs


def fetch_themuse(titles: list) -> list:
    jobs = []
    for title in titles:
        try:
            r = requests.get(
                "https://www.themuse.com/api/public/jobs",
                params={"category": title, "page": 1, "descending": "true"},
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                for j in r.json().get("results", []):
                    loc_parts = [loc.get("name", "") for loc in j.get("locations", [])]
                    jobs.append({
                        "title": j.get("name", ""),
                        "company": j.get("company", {}).get("name", ""),
                        "location": ", ".join(loc_parts),
                        "description": j.get("contents", "")[:800],
                        "url": j.get("refs", {}).get("landing_page", ""),
                        "source": "The Muse",
                    })
        except Exception as e:
            print(f"[jobs] The Muse error ({title}): {e}")
    return jobs


def fetch_remoteok(titles: list) -> list:
    jobs = []
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "job-agent/1.0"},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            for j in data[1:]:
                position = j.get("position", "").lower()
                if any(t.lower() in position for t in titles):
                    jobs.append({
                        "title": j.get("position", ""),
                        "company": j.get("company", ""),
                        "location": j.get("location", "Remote"),
                        "description": j.get("description", "")[:800],
                        "url": j.get("url", ""),
                        "source": "RemoteOK",
                    })
    except Exception as e:
        print(f"[jobs] RemoteOK error: {e}")
    return jobs


def fetch_jsearch(titles: list, locations: list) -> list:
    jobs = []
    if not RAPIDAPI_KEY:
        print("[jobs] RapidAPI key missing, skipping JSearch.")
        return jobs
    for title in titles:
        query = f"{title} in {locations[0]}" if locations else title
        try:
            r = requests.get(
                "https://jsearch.p.rapidapi.com/search",
                headers={
                    "X-RapidAPI-Key": RAPIDAPI_KEY,
                    "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
                },
                params={"query": query, "page": "1", "num_pages": "1"},
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                for j in r.json().get("data", []):
                    city = j.get("job_city", "") or ""
                    state = j.get("job_state", "") or ""
                    loc = f"{city}, {state}".strip(", ")
                    jobs.append({
                        "title": j.get("job_title", ""),
                        "company": j.get("employer_name", ""),
                        "location": loc,
                        "description": j.get("job_description", "")[:800],
                        "url": j.get("job_apply_link", ""),
                        "source": "JSearch",
                    })
        except Exception as e:
            print(f"[jobs] JSearch error ({title}): {e}")
    return jobs


def fetch_serpapi_google_jobs(titles: list, locations: list) -> list:
    jobs = []
    if not SERPAPI_KEY:
        print("[jobs] SerpAPI key missing, skipping Google Jobs.")
        return jobs
    for title in titles:
        query = f"{title} jobs {locations[0]}" if locations else f"{title} jobs"
        try:
            r = requests.get(
                "https://serpapi.com/search.json",
                params={"engine": "google_jobs", "q": query, "api_key": SERPAPI_KEY},
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                for j in r.json().get("jobs_results", []):
                    jobs.append({
                        "title": j.get("title", ""),
                        "company": j.get("company_name", ""),
                        "location": j.get("location", ""),
                        "description": j.get("description", "")[:800],
                        "url": j.get("related_links", [{}])[0].get("link", ""),
                        "source": "Google Jobs",
                    })
        except Exception as e:
            print(f"[jobs] SerpAPI error ({title}): {e}")
    return jobs


def fetch_all_jobs(titles: list, locations: list) -> list:
    raw = []
    raw += fetch_adzuna(titles, locations)
    raw += fetch_themuse(titles)
    raw += fetch_remoteok(titles)
    raw += fetch_jsearch(titles, locations)
    raw += fetch_serpapi_google_jobs(titles, locations)
    return deduplicate(raw)


def deduplicate(jobs: list) -> list:
    seen, out = set(), []
    for j in jobs:
        key = (j.get("title", "").lower().strip(), j.get("company", "").lower().strip())
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


def pre_filter(jobs: list, titles: list) -> list:
    if not titles:
        return jobs
    keywords = set()
    for t in titles:
        for word in t.lower().split():
            if len(word) > 2:
                keywords.add(word)
    filtered = []
    for j in jobs:
        title = j.get("title", "").strip()
        company = j.get("company", "").strip()
        if not title or not company:
            continue
        if any(kw in title.lower() for kw in keywords):
            filtered.append(j)
    return filtered if filtered else jobs
