-- Job Monitor Pipeline Database Schema
-- Run this in your Supabase SQL Editor to set up the database

-- Create jobs table
CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    url TEXT UNIQUE NOT NULL,
    source TEXT,
    date_posted DATE,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_currency TEXT,
    department TEXT,

    -- Filtering fields
    relevant BOOLEAN DEFAULT FALSE,
    filtered_at TIMESTAMPTZ,

    -- Enrichment fields
    description TEXT,
    enriched_at TIMESTAMPTZ,

    -- Scoring fields
    match_score FLOAT,
    match_reasoning TEXT,
    scored_at TIMESTAMPTZ,

    -- Application tracking
    applied BOOLEAN DEFAULT FALSE,
    applied_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for excluding applied jobs from queries
CREATE INDEX IF NOT EXISTS jobs_applied_idx ON jobs (applied) WHERE applied = TRUE;

-- Create seen_jobs table to track previously encountered postings
CREATE TABLE IF NOT EXISTS seen_jobs (
    url_hash TEXT PRIMARY KEY,
    first_seen_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create sources table to manage job posting origins
CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('ashby', 'greenhouse', 'lever', 'vc_job_board', 'career_page', 'playwright', 'workatastartup', 'topstartups', 'consider', 'getro', 'fractionaljobs')),
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable Row Level Security
ALTER TABLE seen_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;

-- Create policies for service role access
CREATE POLICY "Service role full access on jobs" ON jobs
    FOR ALL USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY "Service role full access on seen_jobs" ON seen_jobs
    FOR ALL USING (TRUE) WITH CHECK (TRUE);

CREATE POLICY "Service role full access on sources" ON sources
    FOR ALL USING (TRUE) WITH CHECK (TRUE);

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS jobs_relevant_unenriched_idx
    ON jobs (relevant, enriched_at)
    WHERE relevant = TRUE AND enriched_at IS NULL;

CREATE INDEX IF NOT EXISTS jobs_unscored_idx
    ON jobs (enriched_at, scored_at)
    WHERE enriched_at IS NOT NULL AND scored_at IS NULL;

CREATE INDEX IF NOT EXISTS jobs_url_idx ON jobs (url);
CREATE INDEX IF NOT EXISTS jobs_company_idx ON jobs (company);
CREATE INDEX IF NOT EXISTS jobs_match_score_idx ON jobs (match_score DESC) WHERE match_score IS NOT NULL;

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at
CREATE TRIGGER update_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
