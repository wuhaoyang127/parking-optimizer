"""Single-host persistent release, activation CAS, and execution audit storage."""
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from threading import RLock
from datetime import datetime, UTC
from parking_opt.api.research_runtime import canonical_hash
from parking_opt.api.research_lifecycle import TrialLifecycleMixin

LOGGER = logging.getLogger(__name__)


class ReleaseStore(TrialLifecycleMixin):
    def __init__(self, path: Path, sync="auto"):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.sync = sync if callable(sync) else None
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
        if sync == "auto":
            self._auto_attach()

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
            self.db.execute("INSERT INTO releases (id, hash, data, validation) VALUES (?,?,?,?)",
                            (release.release_id, h, json.dumps(data), None))
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

    # ── 快照持久化（Supabase）──
    def snapshot(self):
        """把当前全部状态序列化为可 JSON 化的快照字典。"""
        with self.lock:
            releases = [list(r) for r in self.db.execute(
                "SELECT id,hash,data,validation,status,trial_started_at,"
                "trial_ratio,research_score FROM releases ORDER BY rowid")]
            active_hash = self.db.execute("SELECT hash FROM active WHERE id=1").fetchone()[0]
            audit = [r[0] for r in self.db.execute("SELECT data FROM audit ORDER BY seq")]
            observations = [list(r) for r in self.db.execute(
                "SELECT scope,lot,data FROM observations")]
            backup = [list(r) for r in self.db.execute(
                "SELECT release_id,backed_up_at,expires_at FROM backup ORDER BY id")]
        return {"releases": releases, "active_hash": active_hash, "audit": audit,
                "observations": observations, "backup": backup}

    def restore(self, snap):
        """用快照覆盖当前本地状态（启动时从 Supabase 恢复）。"""
        with self.lock, self.db:
            self.db.execute("DELETE FROM releases")
            self.db.execute("DELETE FROM audit")
            self.db.execute("DELETE FROM observations")
            self.db.execute("DELETE FROM backup")
            self.db.execute("UPDATE active SET hash=?", (snap.get("active_hash"),))
            for r in snap.get("releases", []):
                self.db.execute(
                    "INSERT INTO releases (id,hash,data,validation,status,"
                    "trial_started_at,trial_ratio,research_score) VALUES (?,?,?,?,?,?,?,?)", r)
            for a in snap.get("audit", []):
                self.db.execute("INSERT INTO audit(data) VALUES (?)", (a,))
            for o in snap.get("observations", []):
                self.db.execute("INSERT INTO observations (scope,lot,data) VALUES (?,?,?)", o)
            for b in snap.get("backup", []):
                self.db.execute(
                    "INSERT INTO backup (release_id,backed_up_at,expires_at) VALUES (?,?,?)", b)

    def attach_sync(self, sync_fn):
        """挂接 Supabase 快照同步，并启动后台定时落盘线程。"""
        self.sync = sync_fn
        threading.Thread(target=self._sync_loop, daemon=True).start()

    def _auto_attach(self):
        """默认路径：从 Supabase 恢复上次快照并启动后台同步；不可用则降级为本地 SQLite。"""
        try:
            from parking_opt.api.research_supabase import pull_state, push_state
            snap = pull_state()
            if snap:
                self.restore(snap)
            self.attach_sync(push_state)
        except Exception:
            LOGGER.warning("车主端持久化不可用，降级为本地 SQLite", exc_info=True)

    def _sync_loop(self):
        last = None
        while True:
            time.sleep(5)
            if self.sync is None:
                continue
            try:
                snap = self.snapshot()
                h = canonical_hash(snap)
                if h != last:
                    self.sync(snap)
                    last = h
            except Exception:
                LOGGER.warning("车主端状态持久化失败（下次启动从上次快照恢复）", exc_info=True)
