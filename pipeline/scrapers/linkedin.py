"""Scrape LinkedIn jobs via the Apify curious_coder/linkedin-jobs-scraper actor.

Unlike the per-company ATS scrapers, this is a market-wide keyword search:
it sweeps keyword x location combinations across all of LinkedIn, which is
how we reach companies that aren't on our curated board list.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from playwright.sync_api import Browser

from .. import config

MAX_JOB_AGE_DAYS = 30

DEFAULT_KEYWORDS = [
    "revenue operations",
    "revops",
    "sales operations",
    "gtm operations",
    "business operations",
]
DEFAULT_LOCATIONS = ["United States", "Remote"]


def _search_url(keyword: str, location: str, tpr_seconds: Optional[int] = None) -> str:
    """Build a public LinkedIn jobs search URL the actor can consume.

    tpr_seconds sets LinkedIn's "date posted" filter (f_TPR); e.g. 604800 = past week.
    """
    params = {"keywords": keyword, "location": location, "position": 1, "pageNum": 0}
    if tpr_seconds:
        params["f_TPR"] = f"r{tpr_seconds}"
    return f"https://www.linkedin.com/jobs/search/?{urllib.parse.urlencode(params)}"


def _parse_salary(raw: str):
    """Best-effort parse of a LinkedIn salary string -> (min, max, currency).

    Only keeps plausible annual figures (>= 1000) so we skip hourly rates,
    which don't fit the integer annual salary columns.
    """
    if not raw:
        return None, None, None
    currency = "USD" if "$" in raw else None
    nums = [int(n.replace(",", "")) for n in re.findall(r"[\d,]{3,}", raw)]
    nums = [n for n in nums if n >= 1000]
    if not nums:
        return None, None, currency
    lo, hi = min(nums), max(nums)
    return lo, (hi if hi != lo else None), currency


def _recent(date_str: Optional[str]) -> bool:
    if not date_str:
        return True  # keep if date unknown
    try:
        d = datetime.fromisoformat(date_str[:10])
    except ValueError:
        return True
    return d >= datetime.now() - timedelta(days=MAX_JOB_AGE_DAYS)


def _run_actor(urls: list[str], count: int) -> list[dict]:
    payload = {"urls": urls, "count": count, "scrapeCompany": False}
    api = (
        f"https://api.apify.com/v2/acts/{config.LINKEDIN_ACTOR}"
        f"/run-sync-get-dataset-items?token={config.APIFY_TOKEN}"
    )
    req = urllib.request.Request(
        api, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def scrape(browser: Browser, source: dict) -> list[dict]:
    """Sweep LinkedIn for the source's keyword x location combinations."""
    name = source.get("name", "LinkedIn")
    if not config.APIFY_TOKEN:
        print(f"    {name}: APIFY_TOKEN not set, skipping")
        return []

    keywords = source.get("keywords", DEFAULT_KEYWORDS)
    locations = source.get("locations", DEFAULT_LOCATIONS)
    count = max(10, source.get("count", 100))  # actor requires count >= 10
    tpr = source.get("posted_within_days")
    tpr = int(tpr) * 86400 if tpr else None  # days -> seconds for LinkedIn f_TPR
    urls = [_search_url(k, loc, tpr) for k in keywords for loc in locations]

    try:
        results = _run_actor(urls, count)
    except urllib.error.HTTPError as e:
        print(f"    {name}: Apify error {e.code} {e.read().decode()[:120]}")
        return []
    except Exception as e:
        print(f"    {name}: error {str(e)[:120]}")
        return []

    jobs = []
    for r in results:
        date_posted = (r.get("postedAt") or "")[:10] or None
        if not _recent(date_posted):
            continue
        url = r.get("link") or r.get("applyUrl") or ""
        title = (r.get("title") or "").strip()
        if not url or not title:
            continue
        smin, smax, scur = _parse_salary(r.get("salary"))
        desc = r.get("descriptionText", "") if config.LINKEDIN_FETCH_DESCRIPTIONS else ""
        jobs.append({
            "title": title,
            "company": (r.get("companyName") or "").strip(),
            "location": (r.get("location") or "").strip(),
            "url": url,
            "source": name,
            "date_posted": date_posted,
            "department": (r.get("jobFunction") or "").strip(),
            "salary_min": smin,
            "salary_max": smax,
            "salary_currency": scur,
            "description": desc,
        })

    print(f"    {name}: {len(jobs)} jobs")
    return jobs
