"""System Status page — diagnostic dashboard.

Streamlit auto-discovers this as a second page in the app sidebar.
Bookmark `/01_System_Status` to glance once a week. If anything here
is red or stale, you'd have caught the May–June incident in week 1
instead of week 5.
"""
import os
from datetime import datetime, timezone, timedelta

import streamlit as st
from dotenv import load_dotenv
load_dotenv()

st.set_page_config(page_title="System Status — Job Match Agent", page_icon="health", layout="wide")
st.title("System Status")
st.caption("Operator dashboard. If anything below is red or stale, something's degraded.")


def _badge(label: str, status: str, color: str) -> str:
    """Tiny inline HTML pill."""
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        'font-weight:700;font-size:13px;padding:4px 12px;border-radius:14px;">'
        f'{label}: {status}</span>'
    )


# -- LLM provider health -----------------------------------------------------
st.subheader("LLM provider chain")
st.caption("`grader.py` tries each in order on every grading call.")

cols = st.columns(3)

# Gemini
with cols[0]:
    has_key = bool(os.getenv("GEMINI_API_KEY"))
    if has_key:
        try:
            from grader import _call_gemini, _gemini_dead
            text = _call_gemini("Reply with one word: PING")
            ok = "PING" in text.upper()
            st.markdown(_badge("Gemini", "ALIVE" if ok else "WEIRD", "#1a8c4e" if ok else "#c47900"), unsafe_allow_html=True)
            st.caption(f"Last reply: `{text.strip()[:40]}`")
        except Exception as e:
            st.markdown(_badge("Gemini", "DEAD", "#c0392b"), unsafe_allow_html=True)
            st.caption(f"Error: `{str(e)[:80]}`")
    else:
        st.markdown(_badge("Gemini", "NO KEY", "#777"), unsafe_allow_html=True)

# Anthropic
with cols[1]:
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    if has_key:
        try:
            from grader import _call_anthropic
            text = _call_anthropic("Reply with one word: PING")
            ok = "PING" in text.upper()
            st.markdown(_badge("Anthropic", "ALIVE" if ok else "WEIRD", "#1a8c4e" if ok else "#c47900"), unsafe_allow_html=True)
            st.caption(f"Last reply: `{text.strip()[:40]}`")
        except Exception as e:
            st.markdown(_badge("Anthropic", "DEAD", "#c0392b"), unsafe_allow_html=True)
            st.caption(f"Error: `{str(e)[:80]}`")
    else:
        st.markdown(_badge("Anthropic", "NO KEY", "#777"), unsafe_allow_html=True)
        st.caption("Add `ANTHROPIC_API_KEY` to unlock cloud fallback")

# Ollama
with cols[2]:
    try:
        from grader import _ollama_alive, OLLAMA_MODEL
        alive = _ollama_alive()
        if alive:
            st.markdown(_badge("Ollama", "ALIVE", "#1a8c4e"), unsafe_allow_html=True)
            st.caption(f"Model: `{OLLAMA_MODEL}`")
        else:
            st.markdown(_badge("Ollama", "UNREACHABLE", "#777"), unsafe_allow_html=True)
            st.caption("Local-dev only; not available on GH Actions.")
    except Exception as e:
        st.markdown(_badge("Ollama", "ERROR", "#c0392b"), unsafe_allow_html=True)
        st.caption(f"{str(e)[:80]}")


# -- Email delivery health ---------------------------------------------------
st.divider()
st.subheader("Email delivery")
gmail_user = os.getenv("GMAIL_USER", "")
gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")
gmail_pass_backup = os.getenv("GMAIL_APP_PASSWORD_BACKUP", "")

cols = st.columns(2)
with cols[0]:
    st.markdown(f"**Sender:** `{gmail_user or '(unset)'}`")
    if gmail_pass:
        st.markdown(_badge("Primary App Password", f"set ({len(gmail_pass)} chars)", "#1a8c4e"), unsafe_allow_html=True)
    else:
        st.markdown(_badge("Primary App Password", "MISSING", "#c0392b"), unsafe_allow_html=True)
    if gmail_pass_backup:
        st.markdown(_badge("Backup App Password", f"set ({len(gmail_pass_backup)} chars)", "#1a8c4e"), unsafe_allow_html=True)
    else:
        st.markdown(_badge("Backup App Password", "not set", "#777"), unsafe_allow_html=True)
        st.caption("Add `GMAIL_APP_PASSWORD_BACKUP` to enable failover.")
with cols[1]:
    st.markdown("**SMTP probe** (does login succeed?)")
    if st.button("Test now", key="smtp_probe"):
        import smtplib
        with st.spinner("Testing..."):
            try:
                with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.login(gmail_user, gmail_pass)
                st.success(f"SMTP login OK as {gmail_user}")
            except Exception as e:
                st.error(f"SMTP failed: {str(e)[:160]}")


# -- Per-user delivery freshness ---------------------------------------------
st.divider()
st.subheader("Per-user delivery freshness")
st.caption("Last sent_jobs entry per profile. Anyone showing > 3 days = degraded.")

try:
    from db import supabase
    profiles = supabase.table("profiles").select("email,full_name").execute().data
    now = datetime.now(timezone.utc)
    rows = []
    for p in profiles:
        em = p.get("email", "")
        last = supabase.table("sent_jobs").select("sent_at").eq("user_email", em).order("sent_at", desc=True).limit(1).execute()
        if last.data:
            sent_at = datetime.fromisoformat(last.data[0]["sent_at"].replace("Z", "+00:00"))
            age_days = (now - sent_at).total_seconds() / 86400
            ago = f"{age_days:.1f}d ago"
            health = "fresh" if age_days < 2 else ("stale" if age_days < 7 else "DEGRADED")
        else:
            sent_at = None
            ago = "(never)"
            health = "DEGRADED"
        rows.append({
            "User": p.get("full_name") or "?",
            "Last email": ago,
            "Health": health,
        })
    st.table(rows)
except Exception as e:
    st.error(f"Couldn't load profile freshness: {str(e)[:140]}")


# -- Recent sent_jobs volume -------------------------------------------------
st.divider()
st.subheader("Sent-jobs volume (last 14 days)")
try:
    from db import supabase
    now = datetime.now(timezone.utc)
    daily = []
    for d in range(13, -1, -1):
        end = now - timedelta(days=d)
        start = end - timedelta(days=1)
        cnt = supabase.table("sent_jobs").select("id", count="exact").gte("sent_at", start.isoformat()).lt("sent_at", end.isoformat()).execute()
        daily.append({"date": start.date().isoformat(), "jobs sent": cnt.count})
    # Tiny built-in chart
    import pandas as pd
    df = pd.DataFrame(daily).set_index("date")
    st.bar_chart(df)
    total = sum(d["jobs sent"] for d in daily)
    avg = total / 14
    st.caption(f"Total last 14 days: **{total}**  |  Avg/day: **{avg:.1f}**  |  Today: **{daily[-1]['jobs sent']}**")
except Exception as e:
    st.error(f"Couldn't load volume chart: {str(e)[:140]}")


# -- Schema drift ------------------------------------------------------------
st.divider()
st.subheader("Schema drift check")
st.caption("Columns the code expects vs what Supabase actually has.")

EXPECTED_COLS = {
    "email", "full_name", "target_titles", "preferred_locations",
    "preferred_industries", "target_companies",
    "min_salary", "target_ote", "match_threshold",
    "job_type", "looking_for", "dealbreakers",
    "resume_text", "resume_summary", "resumes",
}
try:
    from db import supabase
    r = supabase.table("profiles").insert({"email": "schema-probe-status@example.invalid"}).execute()
    actual = set(r.data[0].keys()) if r.data else set()
    supabase.table("profiles").delete().eq("email", "schema-probe-status@example.invalid").execute()
    missing = sorted(EXPECTED_COLS - actual)
    extra = sorted(actual - EXPECTED_COLS - {"id", "created_at", "updated_at"})
    if missing:
        st.error("**Missing columns** (code expects, DB lacks):")
        for c in missing:
            st.markdown(f"- `{c}`")
        st.caption("Run the relevant `ALTER TABLE` from `supabase_setup.sql` against your Supabase project to fix.")
    else:
        st.success("All expected columns present.")
    if extra:
        with st.expander(f"Extra columns ({len(extra)}) — harmless, just unused by code"):
            for c in extra:
                st.markdown(f"- `{c}`")
except Exception as e:
    st.error(f"Schema probe failed: {str(e)[:140]}")


st.divider()
st.caption("Refresh the page to re-probe everything. This dashboard makes no DB writes (except a transient insert/delete for the schema probe).")
