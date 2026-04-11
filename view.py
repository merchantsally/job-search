"""View top job matches from Supabase."""
import argparse
from supabase import create_client
from pipeline import config


def main():
    parser = argparse.ArgumentParser(description="View job matches")
    parser.add_argument("-n", "--limit", type=int, default=25, help="Number of results")
    parser.add_argument("--min-score", type=float, default=0, help="Minimum score")
    parser.add_argument("--all", action="store_true", help="Show all scored jobs")
    args = parser.parse_args()

    supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)

    query = supabase.table("jobs").select(
        "title, company, location, match_score, match_reasoning, url"
    ).not_.is_("match_score", "null")

    if args.min_score > 0:
        query = query.gte("match_score", args.min_score)

    query = query.order("match_score", desc=True)

    if not args.all:
        query = query.limit(args.limit)

    result = query.execute()

    print(f"\n{'='*60}")
    print(f"Top {len(result.data)} Job Matches")
    print(f"{'='*60}\n")

    for i, job in enumerate(result.data, 1):
        score = job["match_score"] or 0
        print(f"{i:2}. [{score:.1f}] {job['title']}")
        print(f"    Company:  {job['company']}")
        print(f"    Location: {job['location']}")
        print(f"    URL:      {job['url']}")
        if job["match_reasoning"]:
            # Truncate reasoning to 100 chars for readability
            reasoning = job["match_reasoning"][:150]
            if len(job["match_reasoning"]) > 150:
                reasoning += "..."
            print(f"    Why:      {reasoning}")
        print()


if __name__ == "__main__":
    main()
