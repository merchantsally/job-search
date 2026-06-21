"""View top job matches from the local CSV store."""
import argparse
from pipeline import config
from pipeline.store import LocalStore


def main():
    parser = argparse.ArgumentParser(description="View job matches")
    parser.add_argument("-n", "--limit", type=int, default=25, help="Number of results")
    parser.add_argument("--min-score", type=float, default=0, help="Minimum score")
    parser.add_argument("--all", action="store_true", help="Show all scored jobs")
    args = parser.parse_args()

    store = LocalStore(config.DATA_DIR)

    jobs = store.get_scored_jobs(min_score=args.min_score)

    if not args.all:
        jobs = jobs[: args.limit]

    print(f"\n{'='*60}")
    print(f"Top {len(jobs)} Job Matches")
    print(f"{'='*60}\n")

    for i, job in enumerate(jobs, 1):
        score = job["match_score"] or 0
        print(f"{i:2}. [{score:.1f}] {job['title']}")
        print(f"    Company:  {job['company']}")
        print(f"    Location: {job['location']}")
        print(f"    URL:      {job['url']}")
        if job["match_reasoning"]:
            # Truncate reasoning to 150 chars for readability
            reasoning = job["match_reasoning"][:150]
            if len(job["match_reasoning"]) > 150:
                reasoning += "..."
            print(f"    Why:      {reasoning}")
        print()


if __name__ == "__main__":
    main()
