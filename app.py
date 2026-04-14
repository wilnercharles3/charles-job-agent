import streamlit as st
import PyPDF2
import io
import db  # Assuming your db.py handles Supabase
import grader  # Assuming your grader.py handles Gemini

def extract_text_from_pdf(uploaded_file):
    try:
        pdf_reader = PyPDF2.PdfReader(uploaded_file)
        text = ""
        for page in pdf_reader.pages:
            content = page.extract_text()
            if content:
                text += content
        return text.strip()
    except Exception as e:
        st.error(f"PDF Extraction Error: {e}")
        return None

st.title("Job Match Agent")
st.write("Fill out your profile, save it, then search for jobs instantly.")

# Form Layout
with st.form("profile_form"):
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Full name")
        email = st.text_input("Email address")
    
    resume_file = st.file_uploader("Upload your resume (PDF or TXT)", type=["pdf", "txt"])
    
    st.subheader("What You're Looking For")
    titles = st.text_input("Job title(s) you're targeting")
    location = st.text_input("Preferred location(s)")
    salary = st.number_input("Minimum base salary (annual)", min_value=0, value=45000)
    job_type = st.selectbox("Job type", ["Remote", "On-site", "Hybrid"])
    looking_for = st.text_area("Tell us what you're looking for")
    dealbreakers = st.text_area("Dealbreakers (optional)")

    submit_button = st.form_submit_button("Save My Profile")

if submit_button:
    if not name or not email:
        st.warning("Please provide at least your name and email.")
    else:
        try:
            resume_text = ""
            resume_summary = "No resume provided"

            if resume_file:
                if resume_file.type == "application/pdf":
                    resume_text = extract_text_from_pdf(resume_file)
                else:
                    resume_text = str(resume_file.read(), "utf-8")

            if resume_text:
                with st.spinner("Summarizing resume with AI..."):
                    # Attempt AI summary, but don't let it crash the save
                    try:
                        resume_summary = grader.summarize_resume(resume_text)
                    except Exception as ai_err:
                        resume_summary = "Summary generation failed."
                        st.warning(f"AI Summary failed, but we'll try to save your profile anyway. Error: {ai_err}")

            # Save to Supabase via your db.py module
            user_data = {
                "name": name,
                "email": email,
                "target_titles": titles,
                "location_pref": location,
                "min_salary": salary,
                "job_type": job_type,
                "looking_for": looking_for,
                "dealbreakers": dealbreakers,
                "resume_summary": resume_summary
            }

            db.save_profile(user_data)
            st.success("\u2705 Profile saved successfully! You can now search for jobs.")
            st.balloons()

        except Exception as e:
            # THIS IS THE KEY: It will tell you exactly what is failing (Supabase, PDF, etc.)
            st.error(f"Critical Error: {e}")
            st.info("Check your Streamlit Secrets for DB_URL and DB_KEY.")
