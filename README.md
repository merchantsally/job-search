# Job Monitor Pipeline

Automated job scraping and AI-scoring system. Scrapes company career pages, fetches full job descriptions, and uses Claude AI to score each role against your personal profile.

## How It Works

The pipeline runs in four phases:

1. **Scrape** - Hits company career pages using Playwright, stores new jobs in Supabase
2. **Filter** - Applies keyword and location rules to identify relevant positions
3. **Enrich** - Fetches full job description text for qualifying positions
4. **Score** - Sends each job + your profile to Claude, returns match scores (0-10)

## Setup

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
# Edit .env with your credentials
```

Required environment variables:
- `SUPABASE_URL` - Your Supabase project URL
- `SUPABASE_SERVICE_KEY` - Supabase service role key
- `ANTHROPIC_API_KEY` - Anthropic API key for Claude

### 3. Set Up Database

1. Create a free Supabase project at https://supabase.com
2. Go to SQL Editor and run the contents of `schema_v2.sql`

### 4. Create Your Profile

```bash
cp profile.example.md profile.md
# Edit profile.md with your background and preferences
```

### 5. Customize Job Sources

Edit `job_sources.json` to add/remove companies. Supported types:
- `ashby` - Ashby ATS (jobs.ashbyhq.com)
- `greenhouse` - Greenhouse (job-boards.greenhouse.io)
- `lever` - Lever (jobs.lever.co)
- `career_page` - Generic career pages
- `workatastartup` - Y Combinator job board

### 6. Adjust Filters (Optional)

Edit `pipeline/config.py` to customize:
- `INCLUDE_KEYWORDS` - Title keywords to include
- `EXCLUDE_KEYWORDS` - Title keywords to exclude
- `US_LOCATION_SIGNALS` - US location patterns
- `MIN_MATCH_SCORE` - Minimum score threshold (default: 5.0)

## Running

```bash
python -m pipeline.run
```

## Scheduling (Optional)

Add to crontab to run twice daily:

```bash
crontab -e
# Add:
0 8,20 * * * cd /path/to/job-monitor-pipeline && /path/to/venv/bin/python -m pipeline.run >> /var/log/job-monitor.log 2>&1
```

## Project Structure

```
job-monitor-pipeline/
├── pipeline/
│   ├── __init__.py
│   ├── config.py        # Configuration and filters
│   ├── run.py           # Main orchestrator
│   ├── filter.py        # Title/location filtering
│   ├── enricher.py      # Job description fetching
│   ├── scorer.py        # Claude AI scoring
│   └── scrapers/
│       ├── __init__.py
│       ├── ashby.py
│       ├── greenhouse.py
│       ├── lever.py
│       ├── career_page.py
│       └── workatastartup.py
├── job_sources.json     # Company sources list
├── profile.example.md   # Profile template
├── schema_v2.sql        # Database schema
├── requirements.txt
└── .env.example
```
