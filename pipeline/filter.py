"""Filter jobs based on title keywords and location signals."""
from . import config


def is_relevant(title: str, location: str) -> bool:
    """
    Determine if a job is relevant based on title and location filters.

    Returns True if:
    - Title contains at least one include keyword
    - Title does NOT contain any exclude keywords
    - Location appears to be US-based (or location is empty/unknown)
    """
    title_lower = title.lower()
    location_lower = location.lower() if location else ""

    # Check for exclude keywords first
    for keyword in config.EXCLUDE_KEYWORDS:
        if keyword in title_lower:
            return False

    # Check for at least one include keyword
    has_include = False
    for keyword in config.INCLUDE_KEYWORDS:
        if keyword in title_lower:
            has_include = True
            break

    if not has_include:
        return False

    # Check location (if provided)
    if location_lower:
        # Check for US signals
        has_us_signal = any(
            signal in location_lower for signal in config.US_LOCATION_SIGNALS
        )

        # Check for non-US signals
        has_non_us_signal = any(
            signal in location_lower for signal in config.NON_US_SIGNALS
        )

        # Exclude if has non-US signal without US signal
        if has_non_us_signal and not has_us_signal:
            return False

    return True


def filter_jobs(jobs: list[dict]) -> list[dict]:
    """
    Filter a list of jobs and return only relevant ones.
    """
    relevant = []
    for job in jobs:
        if is_relevant(job.get("title", ""), job.get("location", "")):
            relevant.append(job)
    return relevant
