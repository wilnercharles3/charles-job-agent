import streamlit as st
    import pandas as pd
    
    if 'user_data' in st.session_state and st.session_state.user_data:
        st.write("...")
        if st.button('Instant Job Scan'):
            with st.spinner('Fetching and grading jobs...'):
                try:
                    # 1. Call job fetching logic from jobs.py (limit to 5-10 jobs)
                    from jobs import fetch_jobs # Assuming fetch_jobs is in jobs.py and takes relevant user_data
                    
                    job_titles_query = st.session_state.user_data.get('target_titles', '')
                    location_query = st.session_state.user_data.get('location_pref', '')
                    
                    # You might need to adjust how jobs are fetched based on jobs.py
                    jobs_df = fetch_jobs(job_titles_query, location_query, num_jobs=7)
                    
                    if not jobs_df.empty:
                        # 2. Use user_data to grade jobs using grader.py
                        from grader import grade_jobs_realtime # Assuming this function exists
                        user_profile_for_grading = {
                            "title": st.session_state.user_data.get('target_titles', ''),
                            "location": st.session_state.user_data.get('location_pref', ''),
                            "salary": str(st.session_state.user_data.get('min_salary', '')), # Ensure it's string
                            "resume_summary": st.session_state.user_data.get('resume_summary', '')
                        }
                        graded_jobs = grade_jobs_realtime(jobs_df, user_profile_for_grading)
                        
                        st.write("### Job Scan Results:")
                        for index, row in graded_jobs.iterrows():
                            rating = row.get('Rating', 'N/A')
                            label = row.get('Label', 'N/A')
                            st.write(f"- {row['Title']} at {row['Company']}: Rating - {rating}, Label - {label}")
                    else:
                        st.write("No jobs found based on your preferences.")
                except Exception as e:
                    st.error(f"An error occurred: {e}")
    else:
        st.write("Please go to the 'Profile' page and enter your details first.")
    
    
