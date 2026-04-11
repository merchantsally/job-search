"""Scrape Greenhouse job boards via the public API (no Playwright needed)."""
import json
import urllib.request
from datetime import datetime, timedelta
from typing import Optional
from playwright.sync_api import Browser


# Max age for jobs (30 days)
MAX_JOB_AGE_DAYS = 30


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string from Greenhouse API."""
    if not date_str:
        return None
    try:
        # Handle ISO format: 2024-01-15T10:30:00-05:00
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


def scrape(browser: Browser, source: dict) -> list[dict]:
    """
    Calls the Greenhouse Job Board API directly.
    URL format: https://job-boards.greenhouse.io/{token}
    API format: https://boards-api.greenhouse.io/v1/boards/{token}/jobs
    """
    url = source["url"].rstrip("/")
    name = source["name"]
    token = url.split("/")[-1]
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    Greenhouse error ({name}): {e}")
        return []

    jobs = []
    for job in data.get("jobs", []):
        # Skip jobs older than 30 days
        first_published = job.get("first_published", "")
        if first_published and not _is_recent(first_published):
            continue

        jobs.append({
            "title": job.get("title", "").strip(),
            "company": name,
            "location": job.get("location", {}).get("name", ""),
            "url": job.get("absolute_url", ""),
            "source": name,
            "date_posted": (first_published or "")[:10] or None,
        })

    print(f"    {name}: {len(jobs)} jobs")
    return [j for j in jobs if j["url"]]
