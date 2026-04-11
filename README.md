# Job Monitor Pipeline

Automated job scraping and AI-powered scoring system. Scrapes 50+ company career pages and VC portfolio job boards, filters for relevant roles, and uses OpenAI to score each position against your personal profile.

## What It Does

The pipeline runs in four phases:

1. **Scrape** - Hits company career pages and VC portfolio boards using Playwright, stores new jobs in Supabase
2. **Filter** - Applies keyword and location rules to identify relevant positions (operations, rev ops, biz ops, etc.)
3. **Enrich** - Fetches full job description text for qualifying positions
4. **Score** - Sends each job + your profile to OpenAI GPT-4, returns match scores (0-10) with reasoning

## Supported Job Sources

| Type | Platform | Examples |
|------|----------|----------|
| `ashby` | Ashby ATS | Anthropic, OpenAI, Stripe, Notion, Figma |
| `greenhouse` | Greenhouse ATS | Airbnb, Discord, Cloudflare, GitLab |
| `lever` | Lever ATS | Plaid |
| `consider` | Consider (VC boards) | A16Z, Sequoia, Greylock, Kleiner Perkins |
| `getro` | Getro (VC boards) | Accel, General Catalyst, Index Ventures |
| `workatastartup` | Y Combinator | YC startup jobs |
| `topstartups` | TopStartups.io | Recently funded startup jobs |
| `fractionaljobs` | FractionalJobs.io | Fractional/part-time executive roles |

**35+ VC Portfolio Boards** including: A16Z, Sequoia, Accel, General Catalyst, Bessemer, Lightspeed, Greylock, Kleiner Perkins, Battery Ventures, GV, IVP, NEA, First Round, Insight Partners, Thrive Capital, 8VC, and more.

---

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/merchantsally/job-search.git
cd job-search
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env
cp profile.example.md profile.md
# Edit both files with your info

# 3. Setup database (see Supabase Setup below)

# 4. Run
python -m pipeline.run

# 5. View results
python view.py
```

---

## Detailed Setup

### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
OPENAI_API_KEY=sk-your-openai-key

# Optional: Healthcheck ping URL (for monitoring)
HEALTHCHECK_URL=https://hc-ping.com/your-uuid
```

**Where to get these:**
- **Supabase**: Create free project at [supabase.com](https://supabase.com) → Settings → API
- **OpenAI**: Get API key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

### 3. Set Up Supabase Database

1. Create a free Supabase project at https://supabase.com
2. Go to **SQL Editor** in the sidebar
3. Paste the contents of `schema_v2.sql` and click **Run**

This creates three tables:
- `jobs` - All scraped job postings with scores
- `seen_jobs` - URL hashes to prevent duplicates
- `sources` - (Optional) Job source configuration

### 4. Create Your Profile

```bash
cp profile.example.md profile.md
```

Edit `profile.md` with your background. This is sent to OpenAI for scoring. Example:

```markdown
# Career Profile

## Background
Revenue Operations leader with 10+ years experience...

## Skills
- Revenue Operations: Salesforce, HubSpot, forecasting...
- Tools: SQL, Tableau, Looker...

## What I'm Looking For
- Role types: Head of Ops, VP Rev Ops, Director Biz Ops
- Company stage: Seed to Series C
- Location: Remote (Canada-based)

## Deal Breakers
- No onsite-only roles
- No junior positions
```

### 5. Customize Job Sources (Optional)

Edit `job_sources.json` to add/remove companies:

```json
{
  "name": "Company Name",
  "url": "https://jobs.ashbyhq.com/company",
  "type": "ashby",
  "enabled": true
}
```

---

## Running the Pipeline

### Run Full Pipeline

```bash
python -m pipeline.run
```

Output shows progress through each phase:
```
==================================================
Job Monitor Pipeline - 2026-04-10 22:21
==================================================

=== Phase 1: Scraping ===
  Scraping: Anthropic
    Anthropic: 125 jobs
  ...
  Total new jobs: 1860

=== Phase 2: Filtering ===
  Processed: 230, Relevant: 43

=== Phase 3: Enriching ===
  Enriched: 32/43

=== Phase 4: Scoring ===
  Scored: 43, Top matches: 3

==================================================
Pipeline Complete!
  New jobs scraped: 1860
  Relevant jobs: 43
  Jobs enriched: 32
  Top matches: 3
```

### View Results

```bash
# Top 25 matches
python view.py

# Top 50 matches
python view.py -n 50

# Only high scores (7+)
python view.py --min-score 7

# All scored jobs
python view.py --all
```

---

## Useful Supabase Queries

Go to **SQL Editor** in Supabase and run these queries:

### View Top Matches

```sql
SELECT
    match_score,
    title,
    company,
    location,
    url,
    match_reasoning
FROM jobs
WHERE match_score IS NOT NULL
ORDER BY match_score DESC
LIMIT 25;
```

### View All Relevant Jobs (Unscored)

```sql
SELECT title, company, location, url, created_at
FROM jobs
WHERE relevant = TRUE
  AND scored_at IS NULL
ORDER BY created_at DESC;
```

### Jobs by Company

```sql
SELECT title, location, match_score, url
FROM jobs
WHERE company ILIKE '%stripe%'
ORDER BY match_score DESC NULLS LAST;
```

### Mark Jobs as Applied

```sql
UPDATE jobs
SET applied = TRUE, applied_at = NOW()
WHERE url = 'https://jobs.example.com/job/12345';
```

### View Applied Jobs

```sql
SELECT title, company, applied_at, url
FROM jobs
WHERE applied = TRUE
ORDER BY applied_at DESC;
```

### Stats Dashboard

```sql
SELECT
    COUNT(*) as total_jobs,
    COUNT(*) FILTER (WHERE relevant = TRUE) as relevant_jobs,
    COUNT(*) FILTER (WHERE match_score IS NOT NULL) as scored_jobs,
    COUNT(*) FILTER (WHERE match_score >= 7) as high_matches,
    COUNT(*) FILTER (WHERE applied = TRUE) as applied
FROM jobs;
```

### Clear Old Jobs (Older than 30 Days)

```sql
DELETE FROM jobs
WHERE created_at < NOW() - INTERVAL '30 days'
  AND applied = FALSE;
```

---

## Scheduling (Optional)

Run twice daily with cron:

```bash
crontab -e
```

Add:
```
0 8,20 * * * cd /path/to/job-search && /path/to/venv/bin/python -m pipeline.run >> /var/log/job-monitor.log 2>&1
```

---

## Configuration

### Adjust Filters

Edit `pipeline/config.py`:

```python
# Keywords to include in job titles
INCLUDE_KEYWORDS = [
    "operations", "ops", "rev ops", "revenue operations",
    "biz ops", "business operations", "strategy",
    "chief of staff", "head of", "director", "vp"
]

# Keywords to exclude
EXCLUDE_KEYWORDS = [
    "engineer", "developer", "software", "security",
    "intern", "junior", "entry level"
]

# Minimum score to highlight as "top match"
MIN_MATCH_SCORE = 5.0
```

### Scoring Model

Default uses `gpt-4o-mini`. Change in `pipeline/config.py`:

```python
SCORING_MODEL = "gpt-4o"  # More accurate, costs more
```

---

## Project Structure

```
job-search/
├── pipeline/
│   ├── __init__.py
│   ├── config.py          # Configuration and filters
│   ├── run.py             # Main orchestrator
│   ├── filter.py          # Title/location filtering
│   ├── enricher.py        # Job description fetching
│   ├── scorer.py          # OpenAI scoring
│   └── scrapers/
│       ├── ashby.py       # Ashby ATS API
│       ├── greenhouse.py  # Greenhouse ATS API
│       ├── lever.py       # Lever ATS (Playwright)
│       ├── consider.py    # Consider VC boards
│       ├── getro.py       # Getro VC boards
│       ├── topstartups.py # TopStartups.io
│       ├── workatastartup.py  # Y Combinator
│       ├── fractionaljobs.py  # FractionalJobs.io
│       └── career_page.py # Generic career pages
├── job_sources.json       # Company sources list
├── profile.md             # Your profile (gitignored)
├── profile.example.md     # Profile template
├── schema_v2.sql          # Database schema
├── view.py                # CLI to view results
├── requirements.txt
└── .env                   # Credentials (gitignored)
```

---

## Troubleshooting

### "No jobs found" for a source
- Check if the company changed their ATS (common)
- Try visiting the URL manually to verify
- Some boards block scrapers (Coatue, for example)

### Enrichment errors
- Some VC job boards block direct access to job pages
- Jobs still get scored with title/company info only

### Scoring not working
- Verify `OPENAI_API_KEY` is set correctly
- Check your OpenAI account has credits

### Database connection errors
- Verify `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are correct
- Make sure you ran `schema_v2.sql` in SQL Editor

---

## License

MIT
