"""Scrape Consider-powered VC portfolio job boards.

Consider is a platform used by many top VCs including:
- Andreessen Horowitz (a16z) - portfoliojobs.a16z.com
- Sequoia Capital - jobs.sequoiacap.com
- Bessemer Venture Partners - jobs.bvp.com
- Lightspeed Venture Partners - jobs.lsvp.com
- Greylock Partners - jobs.greylock.com
- Kleiner Perkins - jobs.kleinerperkins.com
- Battery Ventures - jobs.battery.com
- GV (Google Ventures) - jobs.gv.com
- IVP - careers.ivp.com
- NEA - careers.nea.com
- First Round Capital - jobs.firstround.com
- Bain Capital Ventures - jobs.baincapitalventures.com
"""
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin
from playwright.sync_api import Browser


# Max age for jobs (30 days)
MAX_JOB_AGE_DAYS = 30


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse various date formats."""
    if not date_str:
        return None

    date_str = date_str.strip()

    # Try ISO format first
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        pass

    # Try common formats
    for fmt in ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None


def _is_recent(date_str: str) -> bool:
    """Check if job posting is within MAX_JOB_AGE_DAYS."""
    parsed = _parse_date(date_str)
    if not parsed:
        return True  # Include if date unknown

    cutoff = datetime.now() - timedelta(days=MAX_JOB_AGE_DAYS)
    # Handle timezone-aware dates
    if parsed.tzinfo:
        cutoff = cutoff.replace(tzinfo=parsed.tzinfo)

    return parsed >= cutoff


def scrape(browser: Browser, source: dict) -> list[dict]:
    """
    Scrapes Consider-powered job boards.

    Consider boards render client-side and use infinite scroll.
    We use Playwright to load the page and extract job listings.
    """
    url = source.get("url", "").rstrip("/")
    name = source.get("name", "Consider Board")
    jobs = []
    seen_urls = set()

    # Create page with realistic browser context
    page = browser.new_page(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        # Navigate to jobs page
        jobs_url = f"{url}/jobs" if not url.endswith("/jobs") else url
        page.goto(jobs_url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=20000)

        # Scroll to load more jobs
        for _ in range(10):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)

            # Check if we've loaded enough
            job_links = page.query_selector_all(
                "a[href*='greenhouse.io'], a[href*='lever.co'], "
                "a[href*='ashbyhq.com'], a[href*='workable.com']"
            )
            if len(job_links) > 200:
                break

        # Find external ATS job links (these are the actual job postings)
        external_links = page.query_selector_all(
            "a[href*='greenhouse.io'], a[href*='lever.co'], "
            "a[href*='ashbyhq.com'], a[href*='workable.com']"
        )

        for link in external_links:
            try:
                href = link.get_attribute("href")
                if not href or href in seen_urls:
                    continue

                # Remove tracking params for deduplication
                base_url = href.split("?")[0]
                if base_url in seen_urls:
                    continue
                seen_urls.add(base_url)
                seen_urls.add(href)

                # Get the link text as title
                title = link.inner_text().strip()

                # Skip generic buttons
                if not title or title.lower() in ["apply", "view", "apply now", "view job", ""]:
                    continue

                if len(title) < 3 or len(title) > 200:
                    continue

                # Try to find company from parent container
                company = name.replace(" Portfolio", "").replace(" Jobs", "")
                try:
                    parent = link.evaluate_handle("el => el.closest('[class*=\"job\"], [class*=\"Job\"], [class*=\"item\"], [class*=\"listing\"]')")
                    if parent:
                        company_el = parent.query_selector("[class*='company'], [class*='Company']")
                        if company_el:
                            company = company_el.inner_text().strip() or company
                except Exception:
                    pass

                # Clean company name
                if not company or len(company) > 100:
                    company = name.replace(" Portfolio", "").replace(" Jobs", "")

                # Try to find location from parent container
                location = ""
                try:
                    parent = link.evaluate_handle("el => el.closest('[class*=\"job\"], [class*=\"Job\"], [class*=\"item\"], [class*=\"listing\"]')")
                    if parent:
                        loc_el = parent.query_selector("[class*='location'], [class*='Location']")
                        if loc_el:
                            location = loc_el.inner_text().strip()
                except Exception:
                    pass

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": href,
                    "source": name,
                    "date_posted": None,
                })

            except Exception:
                continue

    except Exception as e:
        print(f"    Consider error ({name}): {e}")
    finally:
        page.close()

    print(f"    {name}: {len(jobs)} jobs")
    return jobs
