"""Scrape Y Combinator's Work at a Startup job board."""
from playwright.sync_api import Browser


# Role filters for customer-facing positions
ROLE_FILTERS = [
    "operations",
    "customer_success",
    "sales",
]


def scrape(browser: Browser, source: dict) -> list[dict]:
    """
    Scrapes workatastartup.com for job listings.
    Filters for operations and customer-facing roles with remote option.
    """
    base_url = source.get("url", "https://www.workatastartup.com/jobs")
    name = source.get("name", "Work at a Startup")
    jobs = []
    seen_urls = set()
    page = browser.new_page()

    try:
        for role_filter in ROLE_FILTERS:
            try:
                # Navigate to filtered job listing
                filter_url = f"{base_url}?role={role_filter}&remote=true"
                page.goto(filter_url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)

                # Scroll to load more jobs
                for _ in range(5):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)

                # Find job cards - they contain .job-name elements
                job_cards = page.query_selector_all(".rounded-md.border")

                for card in job_cards:
                    try:
                        # Find the job title link
                        title_el = card.query_selector(".job-name a")
                        if not title_el:
                            continue

                        href = title_el.get_attribute("href")
                        if not href or href in seen_urls:
                            continue

                        # Skip category links
                        if "/jobs/l/" in href:
                            continue

                        # Make URL absolute
                        if href.startswith("/"):
                            href = f"https://www.workatastartup.com{href}"

                        seen_urls.add(href)

                        # Extract title
                        title = title_el.inner_text().strip()
                        if not title or len(title) < 3 or len(title) > 120:
                            continue

                        # Extract company name - first link or text in card
                        company = name
                        company_links = card.query_selector_all("a")
                        for cl in company_links:
                            cl_href = cl.get_attribute("href") or ""
                            cl_text = cl.inner_text().strip()
                            # Company links typically go to /companies/
                            if "/companies/" in cl_href and cl_text:
                                company = cl_text.split("(")[0].strip()
                                break

                        # Extract location from job-details
                        location = "Remote"
                        details_el = card.query_selector(".job-details")
                        if details_el:
                            details_text = details_el.inner_text().strip()
                            # Remove job type (Fulltime, etc.) and get location
                            if details_text:
                                # Location is after the job type
                                location = details_text

                        jobs.append({
                            "title": title,
                            "company": company,
                            "location": location,
                            "url": href,
                            "source": name,
                        })

                    except Exception:
                        continue

            except Exception as e:
                print(f"    WaaS error for {role_filter}: {e}")
                continue

    except Exception as e:
        print(f"    Work at a Startup error: {e}")
    finally:
        page.close()

    print(f"    {name}: {len(jobs)} jobs")
    return jobs
