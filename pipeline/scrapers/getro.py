"""Scrape Getro-powered VC portfolio job boards.

Getro is a platform used by many top VCs including:
- Accel - jobs.accel.com
- General Catalyst - jobs.generalcatalyst.com
- Index Ventures - indexventures.getro.com
- Khosla Ventures - jobs.khoslaventures.com
- Insight Partners - jobs.insightpartners.com
- Thrive Capital - jobs.thrivecap.com
- 8VC - jobs.8vc.com
- Redpoint Ventures - careers.redpoint.com
- Norwest Venture Partners - careers.nvp.com
- Menlo Ventures - jobs.menlovc.com
- Emergence Capital - talent.emcap.com
"""
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin
from playwright.sync_api import Browser


# Max age for jobs (30 days)
MAX_JOB_AGE_DAYS = 30


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse various date formats from Getro boards."""
    if not date_str:
        return None

    date_str = date_str.strip().lower()
    now = datetime.now()

    # Handle relative dates
    if "today" in date_str:
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
    for fmt in ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%b %d"]:
        try:
            parsed = datetime.strptime(date_str.title(), fmt)
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
    Scrapes Getro-powered job boards.

    Getro boards render client-side and typically show "Showing X jobs".
    We use Playwright to load the page and extract job listings.
    """
    url = source.get("url", "").rstrip("/")
    name = source.get("name", "Getro Board")
    jobs = []
    seen_urls = set()

    # Create page with realistic browser context
    page = browser.new_page(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        # Navigate to jobs page - try with /jobs suffix first, fall back to base URL
        jobs_url = f"{url}/jobs" if not url.endswith("/jobs") else url
        try:
            page.goto(jobs_url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            # Try base URL if /jobs fails
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=20000)

        # Check if page loaded successfully (not redirected to not-found)
        if "not-found" in page.url or page.title() == "":
            print(f"    {name}: board not accessible")
            return []

        # Scroll to load more jobs (Getro uses infinite scroll)
        for _ in range(15):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(800)

        # Strategy 1: Find job cards using common Getro class patterns
        job_cards = page.query_selector_all(
            "[class*='JobCard'], [class*='job-card'], [class*='jobCard'], "
            "[class*='JobListItem'], [class*='job-list-item'], "
            "[data-testid*='job'], article[class*='job'], li[class*='job']"
        )

        # Strategy 2: Look for internal job links
        if len(job_cards) < 5:
            job_cards = page.query_selector_all("a[href*='/companies/'][href*='/jobs/']")

        # Strategy 3: Look for external ATS links (Greenhouse, Lever, Ashby, Workable)
        if len(job_cards) < 5:
            # Find elements that contain external job links
            job_containers = page.query_selector_all(
                "[class*='job-list'], [class*='JobList'], "
                "[class*='job-row'], [class*='job-item']"
            )
            if job_containers:
                job_cards = job_containers

        # Process job cards
        for card in job_cards:
            try:
                # Find the job link - prefer external ATS links
                link = card.query_selector(
                    "a[href*='greenhouse.io'], a[href*='lever.co'], "
                    "a[href*='ashbyhq.com'], a[href*='workable.com']"
                )
                if not link:
                    # Try internal job links
                    link = card.query_selector("a[href*='/jobs/'][href*='/companies/']")
                if not link:
                    # If card itself is a link
                    if card.evaluate("el => el.tagName") == "A":
                        link = card
                    else:
                        link = card.query_selector("a")

                if not link:
                    continue

                href = link.get_attribute("href")
                if not href or href in seen_urls:
                    continue

                # Skip non-job pages (company-only pages, talent network)
                if "/talent-network" in href:
                    continue
                if "/companies/" in href and "/jobs/" not in href:
                    continue

                # Make URL absolute using urljoin
                if not href.startswith("http"):
                    href = urljoin(url + "/", href)

                seen_urls.add(href)

                # Extract title
                title_el = card.query_selector(
                    "h2, h3, h4, "
                    "[class*='title'], [class*='Title'], "
                    "[class*='JobTitle'], [class*='job-title']"
                )
                title = ""
                if title_el:
                    title = title_el.inner_text().strip()

                # If no title found, try the link text
                if not title:
                    link_text = link.inner_text().strip()
                    # Skip generic button texts
                    if link_text.lower() not in ["apply", "view", "see job", "learn more"]:
                        title = link_text.split("\n")[0].strip()

                if not title or len(title) < 3 or len(title) > 200:
                    continue

                # Skip non-job items
                lower_title = title.lower()
                if any(skip in lower_title for skip in [
                    "join", "talent network", "sign up", "create profile",
                    "showing", "apply", "companies"
                ]):
                    continue

                # Extract company name
                company_el = card.query_selector(
                    "[class*='company'], [class*='Company'], "
                    "[class*='CompanyName'], [class*='company-name'], "
                    "[class*='employer'], .job-list-job-company-link"
                )
                company = ""
                if company_el:
                    company = company_el.inner_text().strip()

                # Clean up company name
                if not company or len(company) > 100:
                    company = name.replace(" Portfolio", "").replace(" Jobs", "")

                # Extract location
                loc_el = card.query_selector(
                    "[class*='location'], [class*='Location'], "
                    "[class*='place'], [class*='city']"
                )
                location = loc_el.inner_text().strip() if loc_el else ""

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
                    "source": name,
                    "date_posted": date_posted,
                })

            except Exception:
                continue

        # Strategy 4: If still no jobs, try finding all external ATS links on page
        if len(jobs) < 5:
            external_links = page.query_selector_all(
                "a[href*='boards.greenhouse.io'][href*='/jobs/'], "
                "a[href*='jobs.lever.co'], "
                "a[href*='jobs.ashbyhq.com']"
            )
            for link in external_links:
                try:
                    href = link.get_attribute("href")
                    if not href or href in seen_urls:
                        continue

                    # Skip apply buttons that just link to job
                    link_text = link.inner_text().strip()
                    if link_text.lower() in ["apply", "view", ""]:
                        continue

                    seen_urls.add(href)

                    title = link_text.split("\n")[0].strip()
                    if not title or len(title) < 3 or len(title) > 200:
                        continue

                    # Try to find company from parent
                    company = name.replace(" Portfolio", "").replace(" Jobs", "")
                    parent = link.evaluate_handle("el => el.closest('[class*=\"job\"]')")
                    if parent:
                        try:
                            company_el = parent.query_selector("[class*='company']")
                            if company_el:
                                company = company_el.inner_text().strip() or company
                        except Exception:
                            pass

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": "",
                        "url": href,
                        "source": name,
                        "date_posted": None,
                    })
                except Exception:
                    continue

    except Exception as e:
        print(f"    Getro error ({name}): {e}")
    finally:
        page.close()

    print(f"    {name}: {len(jobs)} jobs")
    return jobs
