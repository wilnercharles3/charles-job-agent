import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

APP_URL = "https://charles-job-agent-9cpadgvzhra8g38wsrjecd.streamlit.app/"


def _send_mail(to_addr: str, subject: str, html: str) -> bool:
    """Send an HTML email via Gmail SMTP_SSL. Returns True on success."""
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        print("Gmail credentials missing, skipping email.")
        return False
    if not to_addr:
        print("No recipient address, skipping email.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_addr
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to_addr, msg.as_string())
        print(f"Email sent to {to_addr}: {subject}")
        return True
    except Exception as e:
        print(f"Email error ({subject}): {e}")
        return False


def send_welcome_email(user_data):
    """Send a welcome email to a first-time user after they save their profile."""
    email = user_data.get("email", "")
    if not email:
        print("No email in user data, skipping welcome email.")
        return False

    first_name = user_data.get("full_name", "there").split()[0]
    titles = user_data.get("target_titles", "Software Engineer")
    titles_str = titles if titles else "Software Engineer"
    location = user_data.get("preferred_locations", "Remote")
    min_salary = user_data.get("min_salary", 0)
    salary_str = f"{min_salary:,}" if min_salary else "0"

    html = f"""<html>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;background:#f4f4f4;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:20px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">

<tr><td style="background:linear-gradient(135deg,#1a73e8,#4285f4);padding:30px;text-align:center;">
  <h1 style="color:#ffffff;margin:0;font-size:24px;">Welcome to Job Match Agent!</h1>
  <p style="color:#e0e0ff;margin:8px 0 0;font-size:14px;">Your AI-powered job search assistant</p>
</td></tr>

<tr><td style="padding:25px 30px 10px;">
  <h2 style="color:#333;margin:0;">Hi {first_name},</h2>
  <p style="color:#555;line-height:1.6;">Thanks for signing up! Your profile is saved and ready to go. Here is how the app works and some tips to get the best results.</p>
</td></tr>

<tr><td style="padding:10px 30px;">
  <h3 style="color:#1a73e8;margin:0 0 8px;">How It Works</h3>
  <p style="color:#555;line-height:1.6;">
    We search <b>5 job boards</b> (Adzuna, The Muse, RemoteOK, JSearch, Google Jobs)
    for positions matching your preferences. Each listing is then <b>graded by AI</b>
    (Google Gemini) against your resume and criteria on a 1-5 star scale. Only the best
    matches (3+ stars) make it to your daily email or instant scan results.</p>
</td></tr>

<tr><td style="padding:10px 30px;">
  <h3 style="color:#1a73e8;margin:0 0 8px;">Tips for Best Results</h3>
  <table width="100%" cellpadding="8" cellspacing="0" style="border:1px solid #e0e0e0;border-radius:6px;">
    <tr style="background:#f8f9fa;"><td style="color:#555;">
      <b>1. Add multiple job titles</b> separated by commas. For example:
      <i>Python Developer, Software Engineer, Backend Developer</i></td></tr>
    <tr><td style="color:#555;">
      <b>2. Upload or paste your resume</b> so the AI can match your skills to job descriptions.</td></tr>
    <tr style="background:#f8f9fa;"><td style="color:#555;">
      <b>3. Set your dealbreakers</b> clearly, like <i>No commission-only, no night shifts</i>.</td></tr>
    <tr><td style="color:#555;">
      <b>4. Use &quot;Remote&quot; as location</b> to search all US remote positions across every board.</td></tr>
  </table>
</td></tr>

<tr><td style="padding:10px 30px;">
  <h3 style="color:#1a73e8;margin:0 0 8px;">What Your Daily Email Looks Like</h3>
  <p style="color:#555;margin:0 0 10px;">Here is an example of how your matched jobs will appear:</p>
  <table width="100%" cellpadding="10" cellspacing="0" style="border:1px solid #e0e0e0;border-radius:6px;">
    <tr style="background:#e8f5e9;">
      <td style="color:#333;"><b>Python Developer</b> at TechCorp<br/>
        <span style="color:#777;">Remote | Adzuna | 4/5 stars</span><br/>
        <span style="color:#1a73e8;">Great match: Python focus, remote, meets salary range.</span></td></tr>
    <tr style="background:#fff3e0;">
      <td style="color:#333;"><b>Junior Software Engineer</b> at StartupXYZ<br/>
        <span style="color:#777;">New York, NY | JSearch | 3/5 stars</span><br/>
        <span style="color:#1a73e8;">Decent match: entry-level, some Python required.</span></td></tr>
    <tr style="background:#e8f5e9;">
      <td style="color:#333;"><b>Backend Engineer</b> at DataFlow Inc<br/>
        <span style="color:#777;">Remote | Google Jobs | 5/5 stars</span><br/>
        <span style="color:#1a73e8;">Strategic match: Python + REST APIs, fully remote, above salary target.</span></td></tr>
  </table>
</td></tr>

<tr><td style="padding:10px 30px;">
  <h3 style="color:#1a73e8;margin:0 0 8px;">Your Current Settings</h3>
  <table width="100%" cellpadding="8" cellspacing="0" style="border:1px solid #e0e0e0;border-radius:6px;">
    <tr style="background:#f8f9fa;"><td width="40%"><b>Job Titles</b></td><td>{titles_str}</td></tr>
    <tr><td><b>Location</b></td><td>{location}</td></tr>
    <tr style="background:#f8f9fa;"><td><b>Min Salary</b></td><td>${salary_str}</td></tr>
  </table>
</td></tr>

<tr><td style="padding:20px 30px;text-align:center;">
  <a href="{APP_URL}" style="display:inline-block;background:#1a73e8;color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:6px;font-size:16px;font-weight:bold;">Open Job Match Agent</a>
  <p style="color:#999;font-size:12px;margin:10px 0 0;">Scan for jobs, update your profile, or adjust your preferences anytime.</p>
</td></tr>

<tr><td style="background:#f8f9fa;padding:20px 30px;text-align:center;border-top:1px solid #e0e0e0;">
  <p style="color:#999;font-size:12px;margin:0;">
    Job Match Agent |
    <a href="{APP_URL}" style="color:#1a73e8;text-decoration:none;">{APP_URL}</a>
  </p>
</td></tr>

</table>
</td></tr></table>
</body>
</html>"""

    return _send_mail(email, "Welcome to Job Match Agent!", html)


def send_profile_update_email(user_data):
    """Send a short confirmation email to a returning user after a profile update."""
    email = user_data.get("email", "")
    if not email:
        print("No email in user data, skipping update email.")
        return False

    first_name = user_data.get("full_name", "there").split()[0]
    titles = user_data.get("target_titles", "") or "(not set)"
    location = user_data.get("preferred_locations", "") or "(not set)"
    min_salary = user_data.get("min_salary", 0)
    salary_str = f"${min_salary:,}" if min_salary else "Any"
    job_type = user_data.get("job_type", "") or "(not set)"

    html = f"""<html>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;background:#f4f4f4;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:20px 0;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">

<tr><td style="background:#1a73e8;padding:18px 26px;">
  <h1 style="color:#ffffff;margin:0;font-size:18px;">Job Match Agent</h1>
  <p style="color:#cfe0ff;margin:2px 0 0;font-size:12px;">Profile updated</p>
</td></tr>

<tr><td style="padding:22px 30px 6px;">
  <p style="color:#333;font-size:15px;margin:0 0 6px;">Hi {first_name},</p>
  <p style="color:#555;font-size:14px;line-height:1.5;margin:0;">Your profile is updated. Your next scan will use these settings:</p>
</td></tr>

<tr><td style="padding:14px 30px;">
  <table width="100%" cellpadding="8" cellspacing="0" style="border:1px solid #e0e0e0;border-radius:6px;font-size:14px;color:#333;">
    <tr style="background:#f8f9fa;"><td width="35%"><b>Job titles</b></td><td>{titles}</td></tr>
    <tr><td><b>Location</b></td><td>{location}</td></tr>
    <tr style="background:#f8f9fa;"><td><b>Min salary</b></td><td>{salary_str}</td></tr>
    <tr><td><b>Job type</b></td><td>{job_type}</td></tr>
  </table>
</td></tr>

<tr><td style="padding:10px 30px 22px;text-align:center;">
  <a href="{APP_URL}" style="display:inline-block;background:#1a73e8;color:#ffffff;text-decoration:none;padding:10px 22px;border-radius:5px;font-size:14px;font-weight:bold;">Open Job Match Agent</a>
</td></tr>

<tr><td style="background:#f8f9fa;padding:14px 30px;text-align:center;border-top:1px solid #e0e0e0;">
  <p style="color:#999;font-size:11px;margin:0;">
    Job Match Agent |
    <a href="{APP_URL}" style="color:#1a73e8;text-decoration:none;">{APP_URL}</a>
  </p>
</td></tr>

</table>
</td></tr></table>
</body>
</html>"""

    return _send_mail(email, "Your Job Match Agent profile was updated", html)
