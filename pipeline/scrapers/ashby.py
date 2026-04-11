"""Scrape Ashby ATS job boards via their public API."""
import json
import urllib.request
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Optional
from playwright.sync_api import Browser


# Max age for jobs (30 days)
MAX_JOB_AGE_DAYS = 30


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse ISO date string from Ashby API."""
    if not date_str:
        return None
    try:
        # Handle ISO format: 2024-01-15T10:30:00.000Z
        return datetime.fromisoformat(date_str.replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        pass
    try:
        # Try just the date part
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except (ValueError, IndexError):
        pass
    return None


def _is_recent(date_str: str) -> bool:
    """Check if job posting is within MAX_JOB_AGE_DAYS."""
    parsed = _parse_date(date_str)
    if not parsed:
        return True  # Include if date unknown
    cutoff = datetime.now() - timedelta(days=MAX_JOB_AGE_DAYS)
    # Make both naive for comparison
    if parsed.tzinfo:
        parsed = parsed.replace(tzinfo=None)
    return parsed >= cutoff


class _StripHTML(HTMLParser):
    """Simple HTML stripper to extract plain text."""
    def __init__(self):
        super().__init__()
        self.result = []

    def handle_data(self, data):
        self.result.append(data)

    def get_text(self):
        return " ".join(self.result)


def _strip_html(html: str) -> str:
    """Remove HTML tags and return plain text."""
    parser = _StripHTML()
    parser.feed(html)
    text = parser.get_text()
    # Normalize whitespace
    return " ".join(text.split())


def _slug_from_url(url: str) -> str:
    """Extract the board slug from an Ashby URL.

    Examples:
        https://jobs.ashbyhq.com/railway -> railway
        https://jobs.ashbyhq.com/anthropic -> anthropic
    """
    return url.rstrip("/").split("/")[-1]


def scrape(browser: Browser, source: dict) -> list[dict]:
    """
    Calls the Ashby Job Board API directly.
    URL format: https://jobs.ashbyhq.com/{slug}
    API format: https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
    """
    url = source["url"]
    name = source["name"]
    slug = _slug_from_url(url)
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"

    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    Ashby error ({name}): {e}")
        return []

    jobs = []
    for job in data.get("jobs", []):
        title = job.get("title", "").strip()
        if not title:
            continue

        # Skip jobs older than 30 days
        published_at = job.get("publishedAt", "")
        if published_at and not _is_recent(published_at):
            continue

        # Extract location
        location = job.get("location", "") or ""
        if job.get("isRemote"):
            location = f"Remote{' - ' + location if location else ''}"

        # Extract compensation if available
        comp = job.get("compensation")
        salary_min = None
        salary_max = None
        salary_currency = None
        if comp:
            salary_min = comp.get("min")
            salary_max = comp.get("max")
            salary_currency = comp.get("currency")

        # Extract description and clean HTML
        description = ""
        if job.get("descriptionHtml"):
            description = _strip_html(job["descriptionHtml"])[:8000]

        job_url = f"https://jobs.ashbyhq.com/{slug}/{job.get('id', '')}"

        jobs.append({
            "title": title,
            "company": name,
            "location": location,
            "url": job_url,
            "source": "ashby",
            "date_posted": (job.get("publishedAt") or "")[:10] or None,
            "department": job.get("department", ""),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "description": description,
        })

    print(f"    {name}: {len(jobs)} jobs")
    return [j for j in jobs if j.get("url")]
