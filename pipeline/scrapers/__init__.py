"""Job board scrapers for different ATS platforms."""
from . import ashby, greenhouse, lever, career_page, workatastartup
from . import topstartups, consider, getro, fractionaljobs

SCRAPERS = {
    "ashby": ashby.scrape,
    "greenhouse": greenhouse.scrape,
    "lever": lever.scrape,
    "career_page": career_page.scrape,
    "playwright": career_page.scrape,  # Alias for generic Playwright scraping
    "workatastartup": workatastartup.scrape,
    "topstartups": topstartups.scrape,
    "consider": consider.scrape,
    "getro": getro.scrape,
    "fractionaljobs": fractionaljobs.scrape,
}

def get_scraper(source_type: str):
    """Get the appropriate scraper function for a source type."""
    return SCRAPERS.get(source_type)
