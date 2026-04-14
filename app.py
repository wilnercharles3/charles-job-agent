

                if 'user_data' in st.session_state and st.session_state.user_data:
                    st.write("---")
                    if st.button('🔍 Instant Job Scan'):
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
                                        "titles": st.session_state.user_data.get('target_titles', ''),
                                        "location": st.session_state.user_data.get('location_pref', ''),
                                        "salary": str(st.session_state.user_data.get('min_salary', '')), # Ensure it's string
                                        "resume_summary": st.session_state.user_data.get('resume_summary', '')
                                    }
                                    graded_jobs = grade_jobs_realtime(jobs_df, user_profile_for_grading)
                                    
                                    st.write("### Job Scan Results:")
                                    for index, row in graded_jobs.iterrows():
                                        rating = row.get('Rating', 'N/A')
                                        label = row.get('Label', 'N/A')
                                        reason = row.get('Reason', 'No reason provided.')
                                        job_title = row.get('Job Title', 'N/A')
                                        company = row.get('Company', 'N/A')
                                        job_url = row.get('URL', '#')
                                        
                                        col1, col2 = st.columns([4, 1])
                                        with col1:
                                            st.markdown(f"**{job_title} at {company}** - [{job_url}]({job_url})")
                                            st.write(f"**Rating:** {rating}, **Label:** {label}")
                                            st.write(f"**Reason:** {reason}")
                                        with col2:
                                            if label == 'Good Match' or label == 'Great Match' or (isinstance(rating, (int, float)) and rating >= 7):
                                                if st.button(f"Email Me {job_title[:10]}...", key=f"email_{index}"):
                                                    # Add email sending logic here if desired, 
                                                    # or just mark it as a feature to implement
                                                    st.toast(f"Email for {job_title} - Feature coming soon!")
                                        st.write("---")
                                else:
                                    st.write("No jobs found for your criteria during the instant scan.")
                            except ImportError as ie:
                                st.error(f"Could not import necessary modules (jobs or grader): {ie}")
                            except Exception as e:
                                st.error(f"An error occurred during the job scan: {e}")
    
    
