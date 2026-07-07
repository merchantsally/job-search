"""Log THIS pipeline's Apify usage, separated from the shared account's other users.

Attribution: curious_coder runs count as ours only when the run INPUT's search
keywords match our set; chronometrica was our actor evaluation. Everything else
(notably fantastic-jobs) belongs to the other developer on the account.

Prints a summary and appends a dated snapshot row to data/apify_usage_log.csv.
"""
import csv
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
TOKEN = os.getenv("APIFY_TOKEN")

OUR_KEYWORDS = {
    "revenue operations", "revops", "sales operations", "gtm operations",
    "business operations", "marketing operations", "revenue strategy",
}
CURIOUS_CODER = "hKByXkMQaC5Qt9UMN"
CHRONOMETRICA = "8qvy6dOaXV7DZUvB"  # our one-time eval actor (resolved by name below if id differs)


def _get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url), timeout=30).read().decode())


def _run_keywords(run):
    kv = run.get("defaultKeyValueStoreId")
    kws = set()
    try:
        inp = _get(f"https://api.apify.com/v2/key-value-stores/{kv}/records/INPUT?token={TOKEN}")
        for u in inp.get("urls", []):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
            if "keywords" in q:
                kws.add(q["keywords"][0].lower())
    except Exception:
        pass
    return kws


def main():
    if not TOKEN:
        print("APIFY_TOKEN not set")
        return
    runs = _get(f"https://api.apify.com/v2/actor-runs?token={TOKEN}&limit=1000&desc=1")["data"]["items"]
    # Resolve actor names once
    names = {}
    for a in {r.get("actId") for r in runs}:
        try:
            d = _get(f"https://api.apify.com/v2/acts/{a}?token={TOKEN}")["data"]
            names[a] = f"{d.get('username')}/{d.get('name')}"
        except Exception:
            names[a] = a

    runs_n = 0
    usd = 0.0
    for r in runs:
        name = names.get(r.get("actId"), "")
        cost = r.get("usageTotalUsd") or 0
        mine = False
        if "chronometrica" in name:
            mine = True  # our actor evaluation
        elif r.get("actId") == CURIOUS_CODER or "curious_coder" in name:
            mine = bool(_run_keywords(r) & OUR_KEYWORDS)
        if mine:
            runs_n += 1
            usd += cost

    print(f"OUR pipeline Apify usage (window of {len(runs)} account runs): {runs_n} runs, ${usd:.2f}")

    log = ROOT / "data" / "apify_usage_log.csv"
    log.parent.mkdir(exist_ok=True)
    new = not log.exists()
    with open(log, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp_utc", "our_runs_in_window", "our_usd_in_window"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), runs_n, f"{usd:.2f}"])
    print(f"appended snapshot to {log}")


if __name__ == "__main__":
    main()
