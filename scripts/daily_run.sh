#!/bin/bash
# Daily job-monitor run, then drop a dated copy of top_matches into Downloads.
# Invoked by launchd (com.jobmonitor.daily). The pipeline has a built-in 1h
# watchdog, so a hung run self-terminates.
set -u

PROJECT="/Users/seeyou/Documents/Codex/job-monitor-pipeline"
DOWNLOADS="/Users/seeyou/Downloads"

cd "$PROJECT" || exit 1

echo "===== $(date '+%Y-%m-%d %H:%M:%S') starting daily run ====="
./venv/bin/python -m pipeline.run >> "$PROJECT/data/scheduler.log" 2>&1

# Copy the refreshed top matches to Downloads, named with today's date.
if [ -f "$PROJECT/data/top_matches.csv" ]; then
  cp "$PROJECT/data/top_matches.csv" \
     "$DOWNLOADS/job_scrape_top_matches_$(date +%Y-%m-%d).csv"
  echo "$(date '+%Y-%m-%d %H:%M:%S') wrote job_scrape_top_matches_$(date +%Y-%m-%d).csv to Downloads"
fi

# Log this pipeline's own Apify usage (separate from the shared account's other users).
./venv/bin/python scripts/track_apify_usage.py >> "$PROJECT/data/scheduler.log" 2>&1
