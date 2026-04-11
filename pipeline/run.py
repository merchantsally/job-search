"""Main orchestrator for the job monitor pipeline."""
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from playwright.sync_api import sync_playwright
from supabase import create_client

from . import config
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


def _url_hash(url: str) -> str:
    """Generate a hash of a URL for deduplication."""
    return hashlib.sha256(url.encode()).hexdigest()[:32]


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


def phase1_scrape(supabase, browser) -> int:
    """Phase 1: Scrape all sources for new jobs."""
    print("\n=== Phase 1: Scraping ===")

    sources = _load_sources()
    if not sources:
        return 0

    # Get existing URL hashes to skip duplicates
    result = supabase.table("seen_jobs").select("url_hash").execute()
    seen_hashes = {row["url_hash"] for row in result.data}

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

    # Insert new jobs into database
    if all_new_jobs:
        # Insert seen_jobs records (deduplicated)
        seen_hashes_to_insert = set()
        seen_records = []
        for j in all_new_jobs:
            url_hash = j.get("url_hash")
            if url_hash and url_hash not in seen_hashes_to_insert:
                seen_hashes_to_insert.add(url_hash)
                seen_records.append({"url_hash": url_hash})

        if seen_records:
            # Insert in batches to avoid issues
            for i in range(0, len(seen_records), 100):
                batch = seen_records[i:i + 100]
                try:
                    supabase.table("seen_jobs").upsert(batch).execute()
                except Exception as e:
                    print(f"  Error inserting seen_jobs batch: {e}")

        # Insert job records (deduplicated by URL)
        seen_urls = set()
        job_records = []
        for j in all_new_jobs:
            url = j.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            record = {
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "location": j.get("location", ""),
                "url": url,
                "source": j.get("source", ""),
                "date_posted": j.get("date_posted"),
                "department": j.get("department", ""),
                "salary_min": j.get("salary_min"),
                "salary_max": j.get("salary_max"),
                "salary_currency": j.get("salary_currency"),
                "description": j.get("description", ""),
            }
            job_records.append(record)

        # Insert in batches
        batch_size = 100
        for i in range(0, len(job_records), batch_size):
            batch = job_records[i : i + batch_size]
            try:
                supabase.table("jobs").upsert(
                    batch, on_conflict="url"
                ).execute()
            except Exception as e:
                print(f"  Error inserting batch: {e}")

    print(f"  Total new jobs: {len(all_new_jobs)}")
    return len(all_new_jobs)


def phase2_filter(supabase) -> int:
    """Phase 2: Filter jobs for relevance."""
    print("\n=== Phase 2: Filtering ===")

    # Get unfiltered jobs
    result = (
        supabase.table("jobs")
        .select("id, title, location")
        .is_("filtered_at", "null")
        .execute()
    )

    jobs = result.data
    relevant_count = 0

    for job in jobs:
        is_match = is_relevant(job.get("title", ""), job.get("location", ""))

        supabase.table("jobs").update(
            {
                "relevant": is_match,
                "filtered_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", job["id"]).execute()

        if is_match:
            relevant_count += 1

    print(f"  Processed: {len(jobs)}, Relevant: {relevant_count}")
    return relevant_count


def phase3_enrich(supabase, browser) -> int:
    """Phase 3: Enrich relevant jobs with full descriptions."""
    print("\n=== Phase 3: Enriching ===")

    # Get relevant jobs without descriptions
    result = (
        supabase.table("jobs")
        .select("id, url, description")
        .eq("relevant", True)
        .is_("enriched_at", "null")
        .limit(config.ENRICH_BATCH_SIZE)
        .execute()
    )

    jobs = result.data
    enriched_count = 0

    for job in jobs:
        # Skip if already has description (from API scraper)
        if job.get("description") and len(job["description"]) >= 200:
            supabase.table("jobs").update(
                {"enriched_at": datetime.utcnow().isoformat()}
            ).eq("id", job["id"]).execute()
            enriched_count += 1
            continue

        # Fetch description from URL
        description = fetch_description(browser, job["url"])

        supabase.table("jobs").update(
            {
                "description": description,
                "enriched_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", job["id"]).execute()

        if description:
            enriched_count += 1
            print(f"    Enriched: {job['url'][:60]}...")

    print(f"  Enriched: {enriched_count}/{len(jobs)}")
    return enriched_count


def phase4_score(supabase) -> list[dict]:
    """Phase 4: Score enriched jobs against user profile."""
    print("\n=== Phase 4: Scoring ===")

    profile = config.load_profile()
    if not profile:
        print("  Warning: No profile.md found")
        return []

    # Get enriched jobs without scores
    result = (
        supabase.table("jobs")
        .select("id, title, company, location, description")
        .eq("relevant", True)
        .not_.is_("enriched_at", "null")
        .is_("scored_at", "null")
        .not_.is_("description", "null")
        .limit(config.SCORE_BATCH_SIZE)
        .execute()
    )

    jobs = result.data
    top_matches = []

    for job in jobs:
        score, reasoning = score_job(
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            description=job.get("description", ""),
            profile=profile,
        )

        supabase.table("jobs").update(
            {
                "match_score": score,
                "match_reasoning": reasoning,
                "scored_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", job["id"]).execute()

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

    print(f"  Scored: {len(jobs)}, Top matches: {len(top_matches)}")
    return top_matches


def main():
    """Run the full pipeline."""
    print(f"\n{'='*50}")
    print(f"Job Monitor Pipeline - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    _ping("start")

    # Initialize clients
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        print("Error: Missing Supabase credentials in .env")
        _ping("fail")
        return

    supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        try:
            # Phase 1: Scrape
            new_jobs = phase1_scrape(supabase, browser)

            # Phase 2: Filter
            relevant = phase2_filter(supabase)

            # Phase 3: Enrich
            enriched = phase3_enrich(supabase, browser)

            # Phase 4: Score
            top_matches = phase4_score(supabase)

            # Summary
            print(f"\n{'='*50}")
            print("Pipeline Complete!")
            print(f"  New jobs scraped: {new_jobs}")
            print(f"  Relevant jobs: {relevant}")
            print(f"  Jobs enriched: {enriched}")
            print(f"  Top matches: {len(top_matches)}")

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


if __name__ == "__main__":
    main()
