-- profiles table
CREATE TABLE IF NOT EXISTS profiles (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    email            text        UNIQUE NOT NULL,
    full_name        text,
    resume_text      text,
    target_titles    text,
    preferred_locations text,
    min_salary       integer,
    preferred_industries text,
    job_type         text,
    ideal_role_summary text,
    created_at       timestamptz DEFAULT now(),
    updated_at       timestamptz DEFAULT now()
);

-- auto-update updated_at on every row update
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
