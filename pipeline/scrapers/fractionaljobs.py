"""Scrape FractionalJobs.io for fractional/part-time executive roles."""
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin
from playwright.sync_api import Browser


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
    for fmt in ["%b %d", "%B %d", "%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"]:
        try:
            parsed = datetime.strptime(date_str, fmt)
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
        return True  # Include if date unknown

    cutoff = datetime.now() - timedelta(days=MAX_JOB_AGE_DAYS)
    return parsed >= cutoff


def scrape(browser: Browser, source: dict) -> list[dict]:
    """
    Scrapes fractionaljobs.io for fractional/part-time job listings.
    Uses Playwright since it's a Webflow site with client-side rendering.
    """
    url = source.get("url", "https://www.fractionaljobs.io/")
    name = source.get("name", "Fractional Jobs")
    jobs = []
    seen_urls = set()

    # Create page with realistic browser context
    page = browser.new_page(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        # Use domcontentloaded instead of networkidle for Webflow sites
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)  # Give Webflow time to hydrate

        # Try to wait for job items to appear
        try:
            page.wait_for_selector(".job-item, [class*='job-item'], [class*='job_item']", timeout=10000)
        except Exception:
            pass  # Continue even if selector not found

        # Scroll to trigger lazy loading
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

        # Click "show more" buttons to load all jobs
        for _ in range(5):
            try:
                show_more = page.query_selector("text=Show more")
                if show_more and show_more.is_visible():
                    show_more.click()
                    page.wait_for_timeout(1500)
                else:
                    break
            except Exception:
                break

        # Find job items
        job_cards = page.query_selector_all(".job-item, [class*='job-item'], [class*='job_item']")

        # Fallback to links if no job cards found
        if len(job_cards) < 3:
            job_cards = page.query_selector_all("a[href*='/job/'], a[href*='job-']")

        for card in job_cards:
            try:
                # Find the link
                if card.evaluate("el => el.tagName") == "A":
                    link = card
                else:
                    link = card.query_selector("a[href*='job'], a.job-item__link-to-job, a")

                if not link:
                    continue

                href = link.get_attribute("href")
                if not href or href in seen_urls:
                    continue

                # Make URL absolute
                if href.startswith("/"):
                    href = urljoin("https://www.fractionaljobs.io", href)

                seen_urls.add(href)

                # Extract title
                title_el = card.query_selector(
                    "h2, h3, h4, "
                    "[class*='title'], [class*='Title'], "
                    "[class*='job-name'], [class*='job_name']"
                )
                title = title_el.inner_text().strip() if title_el else ""

                if not title:
                    # Try getting text from the link itself
                    title = link.inner_text().strip().split("\n")[0]

                if not title or len(title) < 3 or len(title) > 200:
                    continue

                # Skip non-job items
                lower_title = title.lower()
                if any(skip in lower_title for skip in [
                    "show more", "load more", "sign up", "subscribe",
                    "newsletter", "filter", "search"
                ]):
                    continue

                # Extract company name
                company_el = card.query_selector(
                    "[class*='company'], [class*='Company'], "
                    "[class*='org'], [class*='employer']"
                )
                company = company_el.inner_text().strip() if company_el else ""

                if not company or len(company) > 100:
                    company = "Fractional Role"

                # Extract location
                loc_el = card.query_selector(
                    "[class*='location'], [class*='Location'], "
                    "[class*='place'], [class*='city']"
                )
                location = loc_el.inner_text().strip() if loc_el else ""

                # Extract hours/commitment if available
                hours_el = card.query_selector("[class*='hour'], [class*='time'], [class*='commitment']")
                hours = hours_el.inner_text().strip() if hours_el else ""
                if hours:
                    location = f"{location} ({hours})".strip(" ()")

                # Extract date if available
                date_el = card.query_selector(
                    "[class*='date'], [class*='Date'], "
                    "[class*='time'], [class*='posted'], time"
                )
                date_str = ""
                if date_el:
                    date_str = date_el.get_attribute("datetime") or date_el.inner_text().strip()

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
                    "source": "fractionaljobs",
                    "date_posted": date_posted,
                })

            except Exception:
                continue

    except Exception as e:
        print(f"    FractionalJobs error: {e}")
    finally:
        page.close()

    print(f"    {name}: {len(jobs)} jobs")
    return jobs
