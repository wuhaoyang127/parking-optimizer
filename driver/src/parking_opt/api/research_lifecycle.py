"""算法试用与备选区生命周期（状态机 mixin，挂到 ReleaseStore 上）。"""
from datetime import datetime, UTC, timedelta


class TrialLifecycleMixin:
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
