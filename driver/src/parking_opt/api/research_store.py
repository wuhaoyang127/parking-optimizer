"""Single-host persistent release, activation CAS, and execution audit storage."""
import json
from pathlib import Path
import sqlite3
from threading import RLock
from datetime import datetime, UTC, timedelta
from parking_opt.api.research_runtime import canonical_hash


class ReleaseStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS releases (id TEXT PRIMARY KEY, hash TEXT, data TEXT,
                                                 validation TEXT);
            CREATE TABLE IF NOT EXISTS active (id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT);
            INSERT OR IGNORE INTO active VALUES (1, NULL);
            CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS observations (scope TEXT, lot TEXT, data TEXT,
                                                     PRIMARY KEY(scope,lot));
            CREATE TABLE IF NOT EXISTS backup (id INTEGER PRIMARY KEY, release_id TEXT UNIQUE,
                                               backed_up_at TEXT, expires_at TEXT);
        """)
        self._migrate()
        self.db.commit()

    def _migrate(self):
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(releases)")}
        for col, ddl in (("status", "TEXT DEFAULT 'staged'"), ("trial_started_at", "TEXT"),
                         ("trial_ratio", "REAL"), ("research_score", "REAL")):
            if col not in cols:
                self.db.execute(f"ALTER TABLE releases ADD COLUMN {col} {ddl}")

    def list(self):
        with self.lock:
            return [dict(json.loads(data), release_hash=h,
                         validation=json.loads(v) if v else None,
                         status=s, trial_started_at=ts, trial_ratio=tr, research_score=rs)
                    for h, data, v, s, ts, tr, rs in self.db.execute(
                        "SELECT hash,data,validation,status,trial_started_at,trial_ratio,"
                        "research_score FROM releases ORDER BY rowid DESC")]

    def get(self, release_id):
        return next((r for r in self.list() if r["release_id"] == release_id), None)

    def active(self):
        with self.lock:
            h = self.db.execute("SELECT hash FROM active WHERE id=1").fetchone()[0]
            return next((r for r in self.list() if r["release_hash"] == h), None)

    def publish(self, release):
        data = release.model_dump(mode="json")
        h = canonical_hash(data)
        with self.lock:
            old = self.get(release.release_id)
            if old:
                if old["release_hash"] != h:
                    raise ValueError("release_id already exists with different content")
                return old
            self.db.execute("INSERT INTO releases VALUES (?,?,?,NULL)",
                            (release.release_id, h, json.dumps(data)))
            self.db.commit()
            return self.get(release.release_id)

    def validated(self, release_id, evidence):
        with self.lock:
            self.db.execute("UPDATE releases SET validation=? WHERE id=?",
                            (json.dumps(evidence), release_id))
            self.db.commit()
            self.audit({"kind": "validation", "release_id": release_id, "evidence": evidence})
            return self.get(release_id)

    def activate(self, command):
        with self.lock, self.db:
            target = self.get(command.release_id) if command.release_id else None
            if command.release_id and (not target or not target["validation"]
                                      or not target["validation"]["passed"]):
                raise ValueError("release has not passed server validation")
            target_hash = target["release_hash"] if target else None
            cursor = self.db.execute("UPDATE active SET hash=? WHERE id=1 AND hash IS ?",
                                     (target_hash, command.expected_active_hash))
            if cursor.rowcount != 1:
                current = self.active()
                if (current["release_hash"] if current else None) != target_hash:
                    raise ValueError("active release changed; refresh before activating")
            self.db.execute("INSERT INTO audit(data) VALUES (?)", (json.dumps({
                "kind": "activation", "from_hash": command.expected_active_hash,
                "to_hash": target_hash, "at": datetime.now(UTC).isoformat()}),))
            return target

    def trial(self):
        return next((r for r in self.list() if r["status"] == "trial"), None)

    def backups(self):
        with self.lock:
            rows = self.db.execute(
                "SELECT release_id, backed_up_at, expires_at FROM backup ORDER BY id DESC").fetchall()
        return [{"release_id": rid, "backed_up_at": b, "expires_at": e, "release": self.get(rid)}
                for rid, b, e in rows]

    def current(self):
        return {"active": self.active(), "trial": self.trial()}

    def start_trial(self, release_id, ratio, research_score):
        with self.lock, self.db:
            release = self.get(release_id)
            if not release or not release["validation"] or not release["validation"]["passed"]:
                raise ValueError("release has not passed server validation")
            if research_score is None:
                raise ValueError("research_score required before trial")
            self.db.execute("UPDATE releases SET status='awaiting_decision' WHERE status='trial'")
            self.db.execute("UPDATE releases SET status='trial', trial_ratio=?, research_score=?,"
                            " trial_started_at=? WHERE id=?",
                            (float(ratio), float(research_score),
                             datetime.now(UTC).isoformat(), release_id))
            self.audit({"kind": "trial_start", "release_id": release_id,
                        "ratio": float(ratio), "research_score": float(research_score)})
            return self.get(release_id)

    def stop_trial(self):
        with self.lock, self.db:
            current = self.trial()
            if not current:
                raise ValueError("no active trial")
            self.db.execute("UPDATE releases SET status='awaiting_decision' WHERE id=?",
                            (current["release_id"],))
            self.audit({"kind": "trial_stop", "release_id": current["release_id"]})
            return self.get(current["release_id"])

    def set_trial_ratio(self, ratio):
        with self.lock, self.db:
            current = self.trial()
            if not current:
                raise ValueError("no active trial")
            self.db.execute("UPDATE releases SET trial_ratio=? WHERE id=?",
                            (float(ratio), current["release_id"]))
            self.audit({"kind": "trial_ratio", "release_id": current["release_id"],
                        "ratio": float(ratio)})
            return self.get(current["release_id"])

    def decide(self, release_id, decision):
        with self.lock, self.db:
            release = self.get(release_id)
            if not release or release["status"] != "awaiting_decision":
                raise ValueError("release is not awaiting decision")
            if decision == "promote":
                old = self.active()
                if old:
                    self.db.execute(
                        "INSERT INTO backup (release_id, backed_up_at, expires_at) VALUES (?,?,?)",
                        (old["release_id"], datetime.now(UTC).isoformat(),
                         (datetime.now(UTC) + timedelta(days=30)).isoformat()))
                self.db.execute("UPDATE active SET hash=? WHERE id=1", (release["release_hash"],))
                self.db.execute("UPDATE releases SET status='active' WHERE id=?", (release_id,))
            elif decision == "discard":
                self.db.execute("UPDATE releases SET status='discarded' WHERE id=?", (release_id,))
            else:
                raise ValueError("unknown decision")
            self.audit({"kind": "trial_decision", "release_id": release_id, "decision": decision})
            return self.get(release_id)

    def restore_backup(self, release_id):
        with self.lock, self.db:
            backup = next((b for b in self.backups() if b["release_id"] == release_id), None)
            if not backup:
                raise ValueError("backup not found")
            if backup["expires_at"] < datetime.now(UTC).isoformat():
                raise ValueError("backup expired")
            old = self.active()
            if old:
                self.db.execute(
                    "INSERT INTO backup (release_id, backed_up_at, expires_at) VALUES (?,?,?)",
                    (old["release_id"], datetime.now(UTC).isoformat(),
                     (datetime.now(UTC) + timedelta(days=30)).isoformat()))
            self.db.execute("DELETE FROM backup WHERE release_id=?", (release_id,))
            self.db.execute("UPDATE active SET hash=? WHERE id=1",
                            (backup["release"]["release_hash"],))
            self.db.execute("UPDATE releases SET status='active' WHERE id=?", (release_id,))
            self.audit({"kind": "backup_restore", "release_id": release_id})
            return self.get(release_id)

    def delete_backup(self, release_id):
        with self.lock, self.db:
            if not any(b["release_id"] == release_id for b in self.backups()):
                raise ValueError("backup not found")
            self.db.execute("DELETE FROM backup WHERE release_id=?", (release_id,))
            self.db.execute("UPDATE releases SET status='discarded' WHERE id=?", (release_id,))
            self.audit({"kind": "backup_delete", "release_id": release_id})
            return {"deleted": release_id}

    def audit(self, data=None):
        with self.lock:
            if data is not None:
                self.db.execute("INSERT INTO audit(data) VALUES (?)", (json.dumps(data),))
                self.db.commit()
            return [json.loads(row[0]) for row in self.db.execute(
                "SELECT data FROM audit ORDER BY seq DESC LIMIT 100")]

    def observations(self, session_id, lot_id, snapshot=None):
        with self.lock:
            row = self.db.execute("SELECT data FROM observations WHERE scope=? AND lot=?",
                                  (session_id, lot_id)).fetchone()
            old = json.loads(row[0]) if row else None
            if snapshot is not None:
                if old and old["observed_at"] > snapshot["observed_at"]:
                    raise ValueError("OBSERVATION_TIME_MOVED_BACKWARDS")
                self.db.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?)",
                                (session_id, lot_id, json.dumps(snapshot)))
                self.db.commit()
                return snapshot
            return old
