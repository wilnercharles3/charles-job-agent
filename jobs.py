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
REMOTE_WORDS = {"remote", "anywhere", "work from home", "wfh"}


def _is_remote(loc):
    return loc.strip().lower() in REMOTE_WORDS


def fetch_adzuna(titles, locations):
    jobs = []
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("[jobs] Adzuna keys missing, skipping.")
        return jobs
    for title in titles:
        combos = []
        if not locations or all(_is_remote(l) for l in locations):
            combos.append((title, None))
        else:
            for loc in locations:
                combos.append((title, None if _is_remote(loc) else loc))
        for t, loc in combos:
            try:
                params = {
                    "app_id": ADZUNA_APP_ID,
                    "app_key": ADZUNA_APP_KEY,
                    "results_per_page": 10,
                    "what": t,
                    "content-type": "application/json",
                }
                if loc:
                    params["where"] = loc
                r = requests.get(
                    "https://api.adzuna.com/v1/api/jobs/us/search/1",
                    params=params,
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
                print(f"[jobs] Adzuna error ({t}, {loc}): {e}")
    print(f"[jobs] Adzuna: {len(jobs)} jobs")
    return jobs


def fetch_themuse(titles):
    jobs = []
    cats = set()
    for t in titles:
        tl = t.lower()
        if any(w in tl for w in ["python", "software", "developer", "programmer", "engineer", "backend"]):
            cats.add("Software Engineering")
        if any(w in tl for w in ["data", "analyst"]):
            cats.add("Data Science")
        if any(w in tl for w in ["devops", "cloud", "sre"]):
            cats.add("IT")
    if not cats:
        cats.add("Software Engineering")
    for cat in cats:
        try:
            r = requests.get(
                "https://www.themuse.com/api/public/jobs",
                params={"category": cat, "page": 1, "descending": "true"},
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                for j in r.json().get("results", []):
                    locs = [l.get("name", "") for l in j.get("locations", [])]
                    jobs.append({
                        "title": j.get("name", ""),
                        "company": j.get("company", {}).get("name", ""),
                        "location": ", ".join(locs),
                        "description": j.get("contents", "")[:800],
                        "url": j.get("refs", {}).get("landing_page", ""),
                        "source": "The Muse",
                    })
        except Exception as e:
            print(f"[jobs] Muse error ({cat}): {e}")
    print(f"[jobs] The Muse: {len(jobs)} jobs")
    return jobs


def fetch_remoteok(titles):
    jobs = []
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "job-agent/1.0"},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            kws = set()
            for t in titles:
                for w in t.lower().split():
                    if len(w) > 2:
                        kws.add(w)
            for j in data[1:]:
                pos = j.get("position", "").lower()
                tags = " ".join(j.get("tags", [])).lower() if j.get("tags") else ""
                if any(kw in pos or kw in tags for kw in kws):
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
    print(f"[jobs] RemoteOK: {len(jobs)} jobs")
    return jobs


def fetch_jsearch(titles, locations):
    jobs = []
    if not RAPIDAPI_KEY:
        print("[jobs] RapidAPI key missing, skipping JSearch.")
        return jobs
    for title in titles:
        if not locations or all(_is_remote(l) for l in locations):
            query = f"{title} remote"
        else:
            query = f"{title} in {locations[0]}"
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
                for j in r.json().get("data", []) or []:
                    city = j.get("job_city", "") or ""
                    state = j.get("job_state", "") or ""
                    loc = f"{city}, {state}".strip(", ") or ("Remote" if j.get("job_is_remote") else "Unknown")
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
    print(f"[jobs] JSearch: {len(jobs)} jobs")
    return jobs


def fetch_serpapi_google_jobs(titles, locations):
    jobs = []
    if not SERPAPI_KEY:
        print("[jobs] SerpAPI key missing, skipping Google Jobs.")
        return jobs
    for title in titles:
        if not locations or all(_is_remote(l) for l in locations):
            query = f"{title} remote jobs"
        else:
            query = f"{title} jobs {locations[0]}"
        try:
            r = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_jobs",
                    "q": query,
                    "api_key": SERPAPI_KEY,
                },
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                for j in r.json().get("jobs_results", []):
                    rl = j.get("related_links", [])
                    url = rl[0].get("link", "") if rl else ""
                    jobs.append({
                        "title": j.get("title", ""),
                        "company": j.get("company_name", ""),
                        "location": j.get("location", ""),
                        "description": j.get("description", "")[:800],
                        "url": url,
                        "source": "Google Jobs",
                    })
        except Exception as e:
            print(f"[jobs] SerpAPI error ({title}): {e}")
    print(f"[jobs] Google Jobs: {len(jobs)} jobs")
    return jobs


def fetch_all_jobs(titles, locations):
    print(f"[jobs] Fetching for titles={titles}, locations={locations}")
    raw = []
    raw += fetch_adzuna(titles, locations)
    raw += fetch_themuse(titles)
    raw += fetch_remoteok(titles)
    raw += fetch_jsearch(titles, locations)
    raw += fetch_serpapi_google_jobs(titles, locations)
    deduped = deduplicate(raw)
    print(f"[jobs] Total: {len(raw)} raw -> {len(deduped)} deduped")
    return deduped


def deduplicate(jobs):
    seen, out = set(), []
    for j in jobs:
        key = (j.get("title", "").lower().strip(), j.get("company", "").lower().strip())
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


def pre_filter(jobs, titles):
    if not titles:
        return jobs
    kws = set()
    for t in titles:
        for w in t.lower().split():
            if len(w) > 2:
                kws.add(w)
    filtered = []
    for j in jobs:
        title = j.get("title", "").strip()
        company = j.get("company", "").strip()
        if not title or not company:
            continue
        text = (title + " " + j.get("description", "")).lower()
        if any(kw in text for kw in kws):
            filtered.append(j)
    return filtered if filtered else [j for j in jobs if j.get("title", "").strip() and j.get("company", "").strip()]
