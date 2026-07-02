"""Main orchestrator for the job monitor pipeline."""
import hashlib
import json
import os
import signal
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import sync_playwright

from . import config
from .store import LocalStore
from .scrapers import get_scraper
from .filter import is_relevant
from .enricher import fetch_description
from .scorer import score_job


def _ping(status: str = "") -> None:
    """Ping healthchecks.io for monitoring."""
    if not config.HEALTHCHECK_URL:
        return
    try:
        url = config.HEALTHCHECK_URL
        if status:
            url = f"{url}/{status}"
        urllib.request.urlopen(url, timeout=5)
    except Exception:
        pass


def _start_watchdog(timeout_seconds: int) -> threading.Timer:
    """Hard-kill this process if the run runs longer than `timeout_seconds`.

    Guards against a hung browser navigation or stalled network call wedging
    the run indefinitely. Runs on a daemon timer thread, so it fires even if
    the main thread is blocked in native code.
    """
    def _kill():
        hours = timeout_seconds / 3600
        print(
            f"\nWatchdog: run exceeded {hours:.1f}h limit -- killing stuck process.",
            flush=True,
        )
        _ping("fail")
        # SIGKILL can't be caught/ignored, so a truly hung process still dies.
        os.kill(os.getpid(), signal.SIGKILL)

    timer = threading.Timer(timeout_seconds, _kill)
    timer.daemon = True
    timer.start()
    return timer


def _strip_query_params(url: str) -> str:
    """Strip query parameters from URL for deduplication."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _url_hash(url: str) -> str:
    """Generate a hash of a URL for deduplication (ignores query params)."""
    clean_url = _strip_query_params(url)
    return hashlib.sha256(clean_url.encode()).hexdigest()[:32]


def _load_sources() -> list[dict]:
    """Load job sources from job_sources.json."""
    if not config.SOURCES_PATH.exists():
        print("Warning: job_sources.json not found")
        return []
    with open(config.SOURCES_PATH) as f:
        data = json.load(f)
    # Filter out comment entries and entries without URLs
    sources = data.get("sources", [])
    return [s for s in sources if s.get("url") and not s.get("_comment")]


def _scrape_source(browser, source: dict, seen_hashes: set) -> list[dict]:
    """Scrape a single source and return new jobs."""
    source_type = source.get("type", "career_page")
    scraper = get_scraper(source_type)

    if not scraper:
        print(f"  No scraper for type: {source_type}")
        return []

    try:
        jobs = scraper(browser, source)

        # Filter out already-seen jobs
        new_jobs = []
        for job in jobs:
            url_hash = _url_hash(job.get("url", ""))
            if url_hash not in seen_hashes:
                job["url_hash"] = url_hash
                new_jobs.append(job)

        return new_jobs
    except Exception as e:
        print(f"  Error scraping {source.get('name', 'unknown')}: {e}")
        return []


def phase1_scrape(store, browser) -> int:
    """Phase 1: Scrape all sources for new jobs."""
    print("\n=== Phase 1: Scraping ===")

    sources = _load_sources()
    if not sources:
        return 0

    # Get existing URL hashes to skip duplicates
    seen_hashes = store.get_seen_hashes()

    all_new_jobs = []

    # Process sources (could be parallelized with ThreadPoolExecutor)
    for source in sources:
        if not source.get("enabled", True):
            continue
        print(f"  Scraping: {source.get('name', 'unknown')}")
        new_jobs = _scrape_source(browser, source, seen_hashes)
        all_new_jobs.extend(new_jobs)

        # Mark URLs as seen
        for job in new_jobs:
            seen_hashes.add(job.get("url_hash", ""))

    # Insert new jobs into local store
    if all_new_jobs:
        # Mark URL hashes as seen (deduplicated)
        store.add_seen_hashes(j.get("url_hash") for j in all_new_jobs)

        # Insert job records (deduplicated by URL without query params)
        seen_urls = set()
        job_records = []
        for j in all_new_jobs:
            url = j.get("url", "")
            if not url:
                continue
            clean_url = _strip_query_params(url)
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            record = {
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "location": j.get("location", ""),
                "url": clean_url,
                "source": j.get("source", ""),
                "date_posted": j.get("date_posted"),
                "department": j.get("department", ""),
                "employment_type": j.get("employment_type", ""),
                "salary_min": j.get("salary_min"),
                "salary_max": j.get("salary_max"),
                "salary_currency": j.get("salary_currency"),
                "estimated_annual_pay": j.get("estimated_annual_pay", ""),
                "description": j.get("description", ""),
            }
            job_records.append(record)

        store.upsert_jobs(job_records)
        store.save()

    print(f"  Total new jobs: {len(all_new_jobs)}")
    return len(all_new_jobs)


def phase2_filter(store) -> int:
    """Phase 2: Filter jobs for relevance."""
    print("\n=== Phase 2: Filtering ===")

    # Get unfiltered jobs
    jobs = store.get_unfiltered_jobs()
    relevant_count = 0

    for job in jobs:
        is_match = is_relevant(job.get("title", ""), job.get("location", ""))

        store.update_job(
            job["id"],
            {
                "relevant": is_match,
                "filtered_at": datetime.utcnow().isoformat(),
            },
        )

        if is_match:
            relevant_count += 1

    store.save()
    print(f"  Processed: {len(jobs)}, Relevant: {relevant_count}")
    return relevant_count


def phase3_enrich(store, browser) -> int:
    """Phase 3: Enrich relevant jobs with full descriptions and locations.

    Fast path: jobs that already ship with a description (e.g. LinkedIn) are
    stamped enriched instantly, with no cap. Slow path: jobs missing a
    description get a Playwright fetch, capped per run to bound runtime.
    """
    print("\n=== Phase 3: Enriching ===")

    pending = store.get_jobs_to_enrich(None)  # all relevant, not-yet-enriched
    described = [j for j in pending if len(j.get("description") or "") >= 200]
    need_fetch = [j for j in pending if len(j.get("description") or "") < 200]

    # Fast path: already have a description -> just mark enriched (no browser).
    for job in described:
        store.update_job(job["id"], {"enriched_at": datetime.utcnow().isoformat()})
    enriched_count = len(described)

    # Slow path: fetch a description from the job page, capped per run.
    fetch_batch = need_fetch[: config.ENRICH_FETCH_BATCH_SIZE]
    for job in fetch_batch:
        enrichment = fetch_description(browser, job["url"])

        update_data = {
            "description": enrichment.get("description", ""),
            "enriched_at": datetime.utcnow().isoformat(),
        }

        # Fill in location if missing
        if not job.get("location") and enrichment.get("location"):
            update_data["location"] = enrichment["location"]

        store.update_job(job["id"], update_data)

        if enrichment.get("description"):
            enriched_count += 1
            print(f"    Enriched: {job['url'][:60]}...")

    store.save()
    print(
        f"  Enriched: {enriched_count} "
        f"({len(described)} pre-filled, fetched {len(fetch_batch)} of {len(need_fetch)} needing a fetch)"
    )
    return enriched_count


def phase4_score(store) -> list[dict]:
    """Phase 4: Score enriched jobs against user profile."""
    print("\n=== Phase 4: Scoring ===")

    profile = config.load_profile()
    if not profile:
        print("  Warning: No profile.md found")
        return []

    # Get enriched jobs without scores (score them all)
    jobs = store.get_jobs_to_score(None)
    top_matches = []

    for job in jobs:
        score, reasoning = score_job(
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            description=job.get("description", ""),
            profile=profile,
        )

        store.update_job(
            job["id"],
            {
                "match_score": score,
                "match_reasoning": reasoning,
                "scored_at": datetime.utcnow().isoformat(),
            },
        )

        if score >= config.MIN_MATCH_SCORE:
            top_matches.append(
                {
                    "title": job["title"],
                    "company": job["company"],
                    "score": score,
                    "reasoning": reasoning,
                    "url": job.get("url", ""),
                }
            )
            print(f"    [{score:.1f}] {job['title']} @ {job['company']}")

    store.save()
    print(f"  Scored: {len(jobs)}, Top matches: {len(top_matches)}")
    return top_matches


def main():
    """Run the full pipeline."""
    print(f"\n{'='*50}")
    print(f"Job Monitor Pipeline - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    _ping("start")

    # Mark when this run started so we can isolate freshly-scored jobs.
    run_started = datetime.utcnow().isoformat()

    # Guard against a stuck run (e.g. a hung browser navigation).
    watchdog = _start_watchdog(config.MAX_RUNTIME_SECONDS)

    # Initialize local CSV store
    store = LocalStore(config.DATA_DIR)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        try:
            # Phase 1: Scrape
            new_jobs = phase1_scrape(store, browser)

            # Phase 2: Filter
            relevant = phase2_filter(store)

            # Phase 3: Enrich
            enriched = phase3_enrich(store, browser)

            # Phase 4: Score
            top_matches = phase4_score(store)

            # Export matches scoring >= threshold, scored within the recent window
            window_start = (
                datetime.utcnow() - timedelta(hours=config.TOP_MATCHES_WINDOW_HOURS)
            ).isoformat()
            exported = store.export_top_matches(
                config.TOP_MATCHES_PATH,
                min_score=config.TOP_MATCHES_MIN_SCORE,
                since=window_start,
            )

            # Summary
            print(f"\n{'='*50}")
            print("Pipeline Complete!")
            print(f"  New jobs scraped: {new_jobs}")
            print(f"  Relevant jobs: {relevant}")
            print(f"  Jobs enriched: {enriched}")
            print(f"  Top matches: {len(top_matches)}")
            print(f"  Matches >= {config.TOP_MATCHES_MIN_SCORE} (last {config.TOP_MATCHES_WINDOW_HOURS}h): {exported} -> {config.TOP_MATCHES_PATH.name}")

            if top_matches:
                print("\nTop Matches:")
                for match in sorted(top_matches, key=lambda x: x["score"], reverse=True)[:10]:
                    print(f"  [{match['score']:.1f}] {match['title']} @ {match['company']}")
                    print(f"         {match['reasoning']}")

            _ping()

        except Exception as e:
            print(f"\nPipeline error: {e}")
            _ping("fail")
            raise

        finally:
            browser.close()
            watchdog.cancel()


if __name__ == "__main__":
    main()
