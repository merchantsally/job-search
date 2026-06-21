"""Fetch and extract job description text from a job URL."""
import re
import urllib.request
import urllib.error

from playwright.sync_api import Browser


# Location selectors (ordered by specificity)
_LOCATION_SELECTORS = [
    # Workday-specific selectors
    "[data-automation-id='locations']",
    "[data-automation-id='location']",
    "[data-automation-id='jobPostingLocation']",
    "[class*='css-cygeeu']",  # Workday location class
    # Generic selectors
    "[class*='location']",
    "[class*='Location']",
    "[data-testid*='location']",
    "[class*='job-location']",
    "[class*='jobLocation']",
]

# Elements to remove before extracting text
_STRIP_SELECTORS = "script, style, nav, header, footer, noscript, svg, img"

# Minimum characters to consider a description useful
_MIN_LENGTH = 200

# Ordered list of selectors to try for JD content (most specific first)
_CONTENT_SELECTORS = [
    "[class*='job-description']",
    "[class*='jobDescription']",
    "[class*='JobDescription']",
    "[id*='job-description']",
    "[id*='jobDescription']",
    "[class*='description']",
    "[class*='content']",
    "[class*='details']",
    "article",
    "main",
    "body",
]


def fetch_description(browser: Browser, url: str) -> dict:
    """
    Navigate to a job URL, extract description and location.
    Returns dict with "description" and "location" keys.
    """
    page = browser.new_page()
    result = {"description": "", "location": ""}
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)  # Wait for dynamic content

        # Extract location before removing elements
        for selector in _LOCATION_SELECTORS:
            el = page.query_selector(selector)
            if el:
                loc_text = el.inner_text().strip()
                # Clean up location - take first line, limit length
                if loc_text and len(loc_text) < 100:
                    result["location"] = loc_text.split("\n")[0].strip()
                    break

        # Remove noise elements
        page.evaluate(f"""
            document.querySelectorAll('{_STRIP_SELECTORS}').forEach(el => el.remove())
        """)

        # Try selectors from most to least specific
        text = ""
        for selector in _CONTENT_SELECTORS:
            el = page.query_selector(selector)
            if el:
                candidate = el.inner_text()
                if len(candidate.strip()) >= _MIN_LENGTH:
                    text = candidate
                    break

        result["description"] = _clean(text)
        return result

    except Exception as e:
        first_line = str(e).splitlines()[0]
        print(f"    Enricher error for {url}: {first_line}")
        fallback = _fetch_via_http(url)
        if fallback["description"] or fallback["location"]:
            print(f"    Recovered via HTTP fallback: {url[:80]}")
            return fallback
        return result
    finally:
        page.close()


def _fetch_via_http(url: str) -> dict:
    """Plain HTTP fallback for when Playwright errors (e.g. ERR_INVALID_RESPONSE)."""
    result = {"description": "", "location": ""}
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return result

    # Strip script/style/svg blocks, then tags
    html = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) >= _MIN_LENGTH:
        result["description"] = _clean(text)
    return result


def _clean(text: str) -> str:
    """Normalize whitespace and cap length."""
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)[:8000]
