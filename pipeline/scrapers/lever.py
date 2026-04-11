"""Scrape Lever ATS job boards using Playwright."""
from playwright.sync_api import Browser


def scrape(browser: Browser, source: dict) -> list[dict]:
    """
    Scrapes Lever job boards using browser automation.
    URL format: https://jobs.lever.co/{company}
    """
    url = source["url"]
    name = source["name"]
    jobs = []
    page = browser.new_page()

    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        # Find all job posting elements
        for el in page.query_selector_all(".posting, [class*='posting']"):
            try:
                # Find the link element
                link = el.query_selector("a.posting-title, a[href*='/jobs/'], a")
                if not link:
                    continue

                href = link.get_attribute("href")
                if not href:
                    continue

                # Get the title
                title_el = el.query_selector(".posting-title h5, [class*='title']")
                title = title_el.inner_text().strip() if title_el else link.inner_text().strip()

                if not title or len(title) < 3:
                    continue

                # Get location
                loc_el = el.query_selector(
                    ".posting-categories .location, .location, [class*='location']"
                )
                location = loc_el.inner_text().strip() if loc_el else ""

                jobs.append({
                    "title": title,
                    "company": name,
                    "location": location,
                    "url": href,
                    "source": name,
                })
            except Exception:
                continue

    except Exception as e:
        print(f"    Lever error ({name}): {e}")
    finally:
        page.close()

    print(f"    {name}: {len(jobs)} jobs")
    return jobs
