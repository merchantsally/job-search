"""Scrape generic company career pages using Playwright."""
from urllib.parse import urljoin
from playwright.sync_api import Browser


# Generic button titles to skip
SKIP_TITLES = {
    "apply",
    "apply now",
    "view all",
    "view all jobs",
    "see all",
    "see all jobs",
    "learn more",
    "read more",
    "explore",
    "back",
    "home",
    "contact",
    "about",
}


def scrape(browser: Browser, source: dict) -> list[dict]:
    """
    Scrapes generic career pages using Playwright browser automation.
    Looks for anchor tags with job-related keywords.
    """
    url = source["url"]
    name = source["name"]
    jobs = []
    page = browser.new_page()

    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)
        page.wait_for_timeout(2000)  # Extra wait for dynamic content

        # Find links that look like job postings
        selectors = [
            "a[href*='job']",
            "a[href*='position']",
            "a[href*='career']",
            "a[href*='opening']",
            "a[href*='role']",
            "a[href*='apply']",
            "[class*='job'] a",
            "[class*='position'] a",
            "[class*='career'] a",
            "[class*='opening'] a",
        ]

        seen_urls = set()
        for selector in selectors:
            try:
                for link in page.query_selector_all(selector):
                    try:
                        href = link.get_attribute("href")
                        if not href:
                            continue

                        # Convert relative URLs to absolute
                        full_url = urljoin(url, href)

                        # Skip already seen URLs
                        if full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)

                        # Get the link text
                        text = link.inner_text().strip()

                        # Validate text
                        if not text or len(text) < 5 or len(text) > 100:
                            continue

                        # Skip generic navigation links
                        if text.lower() in SKIP_TITLES:
                            continue

                        jobs.append({
                            "title": text,
                            "company": name,
                            "location": "",  # Will be enriched later
                            "url": full_url,
                            "source": "career_page",
                        })
                    except Exception:
                        continue
            except Exception:
                continue

    except Exception as e:
        print(f"    Career page error ({name}): {e}")
    finally:
        page.close()

    print(f"    {name}: {len(jobs)} jobs")
    return jobs
