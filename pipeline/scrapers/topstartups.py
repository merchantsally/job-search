"""Scrape TopStartups.io job board for recently funded startup jobs."""
import re
from datetime import datetime, timedelta
from typing import Optional
from playwright.sync_api import Browser


# Role filters for operations positions
ROLE_FILTERS = [
    "operations",
    "strategy",
    "business",
]

# Max age for jobs (30 days)
MAX_JOB_AGE_DAYS = 30


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string like '2 days ago', 'Mar 15', etc."""
    if not date_str:
        return None

    date_str = date_str.lower().strip()
    now = datetime.now()

    # Handle relative dates
    if "today" in date_str or "just now" in date_str:
        return now
    if "yesterday" in date_str:
        return now - timedelta(days=1)
    if "day" in date_str:
        try:
            days = int(date_str.split()[0])
            return now - timedelta(days=days)
        except (ValueError, IndexError):
            pass
    if "week" in date_str:
        try:
            weeks = int(date_str.split()[0])
            return now - timedelta(weeks=weeks)
        except (ValueError, IndexError):
            pass
    if "month" in date_str:
        try:
            months = int(date_str.split()[0])
            return now - timedelta(days=months * 30)
        except (ValueError, IndexError):
            pass

    # Try parsing absolute dates
    for fmt in ["%b %d", "%B %d", "%Y-%m-%d", "%m/%d/%Y"]:
        try:
            parsed = datetime.strptime(date_str, fmt)
            # Add current year if not present
            if parsed.year == 1900:
                parsed = parsed.replace(year=now.year)
            return parsed
        except ValueError:
            continue

    return None


def _is_recent(date_str: str) -> bool:
    """Check if job posting is within MAX_JOB_AGE_DAYS."""
    parsed = _parse_date(date_str)
    if not parsed:
        # If we can't parse date, include the job
        return True

    cutoff = datetime.now() - timedelta(days=MAX_JOB_AGE_DAYS)
    return parsed >= cutoff


def scrape(browser: Browser, source: dict) -> list[dict]:
    """
    Scrapes topstartups.io/jobs for job listings.
    Filters for operations roles and jobs posted in last 30 days.
    """
    base_url = source.get("url", "https://topstartups.io/jobs/")
    name = source.get("name", "TopStartups.io")
    jobs = []
    seen_urls = set()

    # Create page with realistic browser context
    page = browser.new_page(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        for role_filter in ROLE_FILTERS:
            try:
                # Navigate to filtered job listing
                filter_url = f"{base_url}?role={role_filter}"
                page.goto(filter_url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)

                # Scroll to load more jobs (infinite scroll)
                for _ in range(8):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1200)

                # Find job cards - cards that contain "Posted:" text
                cards = page.query_selector_all(".card.card-body")

                for card in cards:
                    try:
                        text = card.inner_text()

                        # Skip non-job cards (filter form, etc.)
                        if "Posted:" not in text:
                            continue

                        # Find job application link (Ashby, Lever, Greenhouse)
                        job_link = card.query_selector(
                            "a[href*='ashbyhq.com'], "
                            "a[href*='lever.co'], "
                            "a[href*='greenhouse.io'], "
                            "a[href*='workable.com'], "
                            "a[href*='jobs.']"
                        )
                        if not job_link:
                            continue

                        href = job_link.get_attribute("href")
                        if not href or href in seen_urls:
                            continue

                        # Clean up URL - remove utm tracking
                        if "?" in href:
                            href = href.split("?")[0]

                        seen_urls.add(href)

                        # Extract job title from the link text
                        title = job_link.inner_text().strip()
                        if not title or len(title) < 3 or len(title) > 150:
                            continue

                        # Skip non-job links
                        if title.lower() in ["apply", "learn more", "see who works here"]:
                            continue

                        # Extract company name - first link in card
                        company_links = card.query_selector_all("a")
                        company = name
                        for cl in company_links:
                            cl_text = cl.inner_text().strip()
                            # Company link is usually the first meaningful link
                            if cl_text and len(cl_text) > 1 and cl_text != title:
                                company = cl_text
                                break

                        # Extract location from text - usually after company name
                        location = ""
                        lines = text.split("\n")
                        for i, line in enumerate(lines):
                            line = line.strip()
                            # Location line is usually short and before Experience
                            if line and len(line) < 50 and "Experience:" not in line and "Posted:" not in line:
                                if "Remote" in line or "," in line or any(c in line for c in ["New York", "San Francisco", "Los Angeles", "Boston", "Austin", "Seattle", "Chicago", "Denver"]):
                                    location = line
                                    break

                        # Extract posted date
                        date_str = ""
                        date_match = re.search(r"Posted:\s*(.+?)(?:\n|$)", text)
                        if date_match:
                            date_str = date_match.group(1).strip()

                        # Skip jobs older than 30 days
                        if date_str and not _is_recent(date_str):
                            continue

                        # Parse date for database
                        date_posted = None
                        parsed = _parse_date(date_str)
                        if parsed:
                            date_posted = parsed.strftime("%Y-%m-%d")

                        jobs.append({
                            "title": title,
                            "company": company,
                            "location": location,
                            "url": href,
                            "source": name,
                            "date_posted": date_posted,
                        })

                    except Exception:
                        continue

            except Exception as e:
                print(f"    TopStartups error for {role_filter}: {e}")
                continue

    except Exception as e:
        print(f"    TopStartups error: {e}")
    finally:
        page.close()

    print(f"    {name}: {len(jobs)} jobs")
    return jobs
