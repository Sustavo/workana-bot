import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Tracker:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.conn.close()

    # ── jobs_seen ─────────────────────────────────────────
    def upsert_job(self, slug: str, title: str, url: str, state: str) -> None:
        now = _now()
        self.conn.execute(
            """
            INSERT INTO jobs_seen (slug, title, url, first_seen_at, last_seen_at, state)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                state = CASE
                    WHEN jobs_seen.state IN ('drafted','sent') THEN jobs_seen.state
                    ELSE excluded.state
                END
            """,
            (slug, title, url, now, now, state),
        )
        self.conn.commit()

    def job_state(self, slug: str) -> str | None:
        row = self.conn.execute("SELECT state FROM jobs_seen WHERE slug = ?", (slug,)).fetchone()
        return row["state"] if row else None

    # ── drafts ────────────────────────────────────────────
    def save_draft(self, slug: str, payload: dict) -> None:
        self.conn.execute(
            """
            INSERT INTO drafts (slug, payload_json, created_at, status)
            VALUES (?, ?, ?, 'pending')
            ON CONFLICT(slug) DO UPDATE SET
                payload_json = excluded.payload_json,
                created_at = excluded.created_at,
                status = 'pending'
            """,
            (slug, json.dumps(payload, ensure_ascii=False), _now()),
        )
        self.conn.commit()

    def list_pending_drafts(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT slug, payload_json, created_at FROM drafts WHERE status = 'pending'"
        ).fetchall()
        return [{"slug": r["slug"], "payload": json.loads(r["payload_json"]), "created_at": r["created_at"]} for r in rows]

    def all_draft_slugs(self) -> set[str]:
        """Todas as vagas que JÁ têm draft (pendente/enviado/rejeitado) — não re-enfileirar."""
        rows = self.conn.execute("SELECT slug FROM drafts").fetchall()
        return {r["slug"] for r in rows}

    def summary(self) -> dict:
        """Contagens pra exibir no início do scrape: jobs_seen por state e drafts por status."""
        jobs = {
            r["state"]: r["n"]
            for r in self.conn.execute(
                "SELECT state, COUNT(*) AS n FROM jobs_seen GROUP BY state"
            ).fetchall()
        }
        drafts = {
            r["status"]: r["n"]
            for r in self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM drafts GROUP BY status"
            ).fetchall()
        }
        return {"jobs": jobs, "drafts": drafts}

    def mark_draft(self, slug: str, status: str) -> None:
        assert status in {"approved", "sent", "rejected"}
        self.conn.execute("UPDATE drafts SET status = ? WHERE slug = ?", (status, slug))
        self.conn.commit()

    # ── submissions ───────────────────────────────────────
    def record_submission(self, slug: str, amount: float, delivery_time: str, content: str) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO submissions (slug, sent_at, amount, delivery_time, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            (slug, _now(), amount, delivery_time, content),
        )
        self.conn.commit()
