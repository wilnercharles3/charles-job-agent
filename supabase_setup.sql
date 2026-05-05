-- profiles table
CREATE TABLE IF NOT EXISTS profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text UNIQUE NOT NULL,
    full_name text,
    resume_text text,
    resume_summary text,
    target_titles text,
    preferred_locations text,
    preferred_industries text,
    target_companies text,
    min_salary integer,
    target_ote integer,
    match_threshold integer DEFAULT 50,
    job_type text,
    looking_for text,
    dealbreakers text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- auto-update updated_at on every row change
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_profiles_updated_at ON profiles;
CREATE TRIGGER trg_profiles_updated_at
    BEFORE UPDATE ON profiles
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();


-- sent_jobs table (tracks which jobs were emailed to which user)
CREATE TABLE IF NOT EXISTS sent_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email text NOT NULL,
    job_title text NOT NULL,
    company text NOT NULL,
    source text,
    sent_at timestamptz DEFAULT now()
);

-- index for fast lookups by email + job
CREATE INDEX IF NOT EXISTS idx_sent_jobs_lookup
    ON sent_jobs (user_email, job_title, company);

-- migration: add preferred_industries to existing deployments
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS preferred_industries text;

-- migration: add target_ote, match_threshold, target_companies for richer matching
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS target_ote integer;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS match_threshold integer DEFAULT 50;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS target_companies text;
