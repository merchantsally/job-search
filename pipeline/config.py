"""Configuration for the job monitor pipeline."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Directory paths
ROOT_DIR = Path(__file__).parent.parent
PROFILE_PATH = ROOT_DIR / "profile.md"
SOURCES_PATH = ROOT_DIR / "job_sources.json"
DATA_DIR = ROOT_DIR / "data"  # Local CSV storage (replaces Supabase)

# OpenAI API
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SCORING_MODEL = "gpt-5.4-nano"

# Apify (LinkedIn jobs source)
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
LINKEDIN_ACTOR = "curious_coder~linkedin-jobs-scraper"  # $1/1k results, descriptions bundled
# Descriptions are bundled free with this actor and required by the scorer, so
# default on. Set LINKEDIN_FETCH_DESCRIPTIONS=0 to omit them (jobs won't be scored).
LINKEDIN_FETCH_DESCRIPTIONS = os.getenv("LINKEDIN_FETCH_DESCRIPTIONS", "1").lower() not in ("0", "false", "no", "")

# Optional monitoring
HEALTHCHECK_URL = os.getenv("HEALTHCHECK_URL", "")

# Pipeline settings
MAX_SCRAPE_WORKERS = 2  # Parallel browser instances
# Jobs that already ship with a description (e.g. LinkedIn) are enriched instantly
# with no cap; this only limits slow Playwright description fetches per run.
ENRICH_FETCH_BATCH_SIZE = 100
MIN_MATCH_SCORE = 5.0  # Minimum score (0-10) for the printed summary list
TOP_MATCHES_MIN_SCORE = 6.0  # Write every job scoring >= this to data/top_matches.csv
TOP_MATCHES_WINDOW_HOURS = 24  # Only include jobs scored within this many hours
TOP_MATCHES_PATH = DATA_DIR / "top_matches.csv"

# Watchdog: hard-kill the run if it exceeds this many seconds (stuck-process guard)
MAX_RUNTIME_SECONDS = int(os.getenv("MAX_RUNTIME_SECONDS", str(60 * 60)))  # 1h

# Load profile content
def load_profile() -> str:
    """Load the user's profile from profile.md"""
    if PROFILE_PATH.exists():
        return PROFILE_PATH.read_text()
    return ""

# Title keywords to INCLUDE (case-insensitive)
INCLUDE_KEYWORDS = [
    "operations",
    "ops",
    "revenue operations",
    "rev ops",
    "revops",
    "business operations",
    "biz ops",
    "bizops",
    "sales operations",
    "sales ops",
    "head of",
    "director",
    "vp",
    "chief",
    "fractional",
    "consulting",
    "consultant",
    "strategy",
    "strategic",
    "gtm",
    "go-to-market",
]

# Title keywords to EXCLUDE (case-insensitive)
EXCLUDE_KEYWORDS = [
    "engineer",
    "engineering",
    "developer",
    "software",
    "swe",
    "frontend",
    "backend",
    "fullstack",
    "devops",
    "sre",
    "designer",
    "design",
    "ux",
    "ui",
    "data scientist",
    "ml",
    "machine learning",
    "intern",
    "internship",
    "junior",
    "entry level",
    "associate",
    "account executive",
    "sdr",
    "bdr",
    "ae",
]

# US location signals (include jobs with these)
US_LOCATION_SIGNALS = [
    "remote",
    "united states",
    "usa",
    "us",
    "new york",
    "san francisco",
    "los angeles",
    "chicago",
    "boston",
    "seattle",
    "austin",
    "denver",
    "miami",
    "atlanta",
    "portland",
    "philadelphia",
    "phoenix",
    "dallas",
    "houston",
    "san diego",
    "remote - us",
    "remote (us)",
    "remote, us",
    "anywhere in us",
    "canada",
    "vancouver",
    "toronto",
    "remote - canada",
    "remote (canada)",
    "north america",
]

# Non-US location signals (exclude unless paired with US/Canada signal)
NON_US_SIGNALS = [
    "uk",
    "united kingdom",
    "london",
    "europe",
    "emea",
    "apac",
    "asia",
    "india",
    "bangalore",
    "mumbai",
    "australia",
    "sydney",
    "melbourne",
    "germany",
    "berlin",
    "france",
    "paris",
    "spain",
    "madrid",
    "brazil",
    "mexico",
    "latam",
    "singapore",
    "hong kong",
    "japan",
    "tokyo",
]
