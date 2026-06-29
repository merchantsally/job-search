"""Local CSV-backed storage, replacing Supabase.

Two CSV files under ``data/`` mirror the old tables:
  - ``jobs.csv``       -> the ``jobs`` table
  - ``seen_jobs.csv``  -> the ``seen_jobs`` table (URL-hash dedup set)

The pipeline keeps everything in memory and persists with ``save()``.
"""
import csv
import re
import sys
from pathlib import Path

# Job descriptions can be large; lift the CSV field size cap.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

# Full column set for the jobs table, in stable file order.
JOB_COLUMNS = [
    "id",
    "title",
    "company",
    "location",
    "url",
    "source",
    "date_posted",
    "department",
    "salary_min",
    "salary_max",
    "salary_currency",
    "description",
    "relevant",
    "filtered_at",
    "enriched_at",
    "match_score",
    "match_reasoning",
    "scored_at",
    "applied",
    "applied_at",
    "created_at",
    "updated_at",
]

INT_FIELDS = {"id", "salary_min", "salary_max"}
FLOAT_FIELDS = {"match_score"}
BOOL_FIELDS = {"relevant", "applied"}


def _decode(field: str, raw: str):
    """Convert a CSV string cell back to a typed Python value."""
    if raw == "":
        # Empty cell means SQL NULL / unset.
        return False if field in BOOL_FIELDS else None
    if field in INT_FIELDS:
        try:
            return int(raw)
        except ValueError:
            return None
    if field in FLOAT_FIELDS:
        try:
            return float(raw)
        except ValueError:
            return None
    if field in BOOL_FIELDS:
        return raw.strip().lower() in ("true", "1", "yes")
    return raw


def _encode(field: str, value) -> str:
    """Convert a typed Python value to a CSV string cell."""
    if value is None:
        return ""
    if field in BOOL_FIELDS:
        return "true" if value else "false"
    return str(value)


def _dedup_key(job: dict) -> tuple:
    """Collapse near-duplicate postings (same role across many city pages).

    LinkedIn reposts one remote role to multiple city URLs, so URL dedup
    misses them; keying on normalized (company, title) folds them into one.
    """
    def norm(s):
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()

    return (norm(job.get("company")), norm(job.get("title")))


class LocalStore:
    """Tiny CSV-backed replacement for the Supabase client."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_path = self.data_dir / "jobs.csv"
        self.seen_path = self.data_dir / "seen_jobs.csv"
        self.jobs: list[dict] = []
        self.seen: set[str] = set()
        self._next_id = 1
        self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        if self.jobs_path.exists():
            with open(self.jobs_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    job = {c: _decode(c, row.get(c, "")) for c in JOB_COLUMNS}
                    self.jobs.append(job)
            ids = [j["id"] for j in self.jobs if isinstance(j.get("id"), int)]
            self._next_id = (max(ids) + 1) if ids else 1

        if self.seen_path.exists():
            with open(self.seen_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    h = row.get("url_hash", "")
                    if h:
                        self.seen.add(h)

    # ------------------------------------------------------------------ save
    def save(self) -> None:
        tmp = self.jobs_path.with_suffix(".csv.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=JOB_COLUMNS)
            writer.writeheader()
            for job in self.jobs:
                writer.writerow({c: _encode(c, job.get(c)) for c in JOB_COLUMNS})
        tmp.replace(self.jobs_path)

        tmp = self.seen_path.with_suffix(".csv.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["url_hash"])
            for h in sorted(self.seen):
                writer.writerow([h])
        tmp.replace(self.seen_path)

    # ------------------------------------------------------------- seen_jobs
    def get_seen_hashes(self) -> set:
        return set(self.seen)

    def add_seen_hashes(self, hashes) -> None:
        self.seen.update(h for h in hashes if h)

    # ------------------------------------------------------------------ jobs
    def upsert_jobs(self, records: list[dict]) -> None:
        """Insert new jobs; for an existing URL, update only provided columns.

        Also skips near-duplicate postings (same company+title under a different
        URL, e.g. one remote role reposted to many city pages) so duplicates are
        never stored, filtered, or scored.
        """
        by_url = {j["url"]: j for j in self.jobs if j.get("url")}
        seen_keys = {_dedup_key(j) for j in self.jobs if all(_dedup_key(j))}
        for record in records:
            url = record.get("url")
            if not url:
                continue
            existing = by_url.get(url)
            if existing:
                for key, value in record.items():
                    existing[key] = value
                continue
            key = _dedup_key(record)
            if all(key) and key in seen_keys:
                continue  # near-duplicate of an existing posting; drop it
            job = {c: None for c in JOB_COLUMNS}
            job["id"] = self._next_id
            self._next_id += 1
            job["relevant"] = False
            job["applied"] = False
            job.update(record)
            self.jobs.append(job)
            by_url[url] = job
            if all(key):
                seen_keys.add(key)

    def _get_by_id(self, job_id):
        for job in self.jobs:
            if job.get("id") == job_id:
                return job
        return None

    def update_job(self, job_id, fields: dict) -> None:
        job = self._get_by_id(job_id)
        if job is not None:
            job.update(fields)

    # -------------------------------------------------------------- queries
    def get_unfiltered_jobs(self) -> list[dict]:
        """jobs WHERE filtered_at IS NULL."""
        return [j for j in self.jobs if not j.get("filtered_at")]

    def get_jobs_to_enrich(self, limit: int) -> list[dict]:
        """jobs WHERE relevant AND enriched_at IS NULL."""
        out = [j for j in self.jobs if j.get("relevant") and not j.get("enriched_at")]
        return out[:limit]

    def get_jobs_to_score(self, limit: int) -> list[dict]:
        """jobs WHERE relevant AND enriched_at IS NOT NULL AND scored_at IS NULL AND description IS NOT NULL."""
        out = [
            j
            for j in self.jobs
            if j.get("relevant")
            and j.get("enriched_at")
            and not j.get("scored_at")
            and j.get("description")
        ]
        return out[:limit]

    def get_scored_jobs(self, min_score: float = 0.0) -> list[dict]:
        """jobs WHERE match_score IS NOT NULL [AND match_score >= min_score], ordered desc."""
        out = [j for j in self.jobs if j.get("match_score") is not None]
        if min_score > 0:
            out = [j for j in out if j["match_score"] >= min_score]
        out.sort(key=lambda j: j["match_score"], reverse=True)
        return out

    # ------------------------------------------------------------- exports
    def export_top_matches(self, path: Path, min_score: float = 0.0, since: str = None) -> int:
        """Write every job scoring >= `min_score` (by match_score desc) to a CSV snapshot.

        If `since` (an ISO timestamp) is given, only jobs scored at or after that
        time are included -- i.e. records fresh from the latest run.
        """
        columns = [
            "rank",
            "match_score",
            "title",
            "company",
            "location",
            "url",
            "match_reasoning",
        ]
        scored = self.get_scored_jobs(min_score)
        if since is not None:
            scored = [j for j in scored if j.get("scored_at") and j["scored_at"] >= since]
        # Collapse multi-city repostings of the same role (scored is sorted desc,
        # so the kept instance is the highest-scoring one).
        seen, top = set(), []
        for job in scored:
            key = _dedup_key(job)
            if key in seen:
                continue
            seen.add(key)
            top.append(job)
        tmp = Path(path).with_suffix(".csv.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for rank, job in enumerate(top, 1):
                writer.writerow(
                    {
                        "rank": rank,
                        "match_score": job.get("match_score"),
                        "title": job.get("title", ""),
                        "company": job.get("company", ""),
                        "location": job.get("location", ""),
                        "url": job.get("url", ""),
                        "match_reasoning": job.get("match_reasoning", ""),
                    }
                )
        tmp.replace(path)
        return len(top)
