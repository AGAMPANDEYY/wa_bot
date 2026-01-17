import os
import sqlite3
import time
from typing import List, Optional, Dict, Any

try:
    from supabase import create_client
except Exception:  # pragma: no cover - optional dependency
    create_client = None


def _now_epoch() -> int:
    return int(time.time())


class SQLiteDatabase:
    """SQLite database for ground truth + audit logging"""

    def __init__(self, db_path: str = "data.db"):
        self.db_path = db_path
        self.init_db()

    def get_conn(self):
        """Get database connection"""
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        return conn

    def init_db(self):
        """Initialize database schema"""
        conn = self.get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                due_at_epoch INTEGER NOT NULL,
                status TEXT DEFAULT 'active',
                category TEXT,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                mem0_memory_id TEXT,
                updated_at INTEGER DEFAULT (strftime('%s', 'now')),
                last_notified_at INTEGER,
                reschedule_count INTEGER DEFAULT 0,
                last_rescheduled_at INTEGER
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS preferences (
                user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                mem0_memory_id TEXT,
                updated_at INTEGER DEFAULT (strftime('%s', 'now')),
                PRIMARY KEY (user_id, key)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                action TEXT NOT NULL,
                details TEXT,
                timestamp INTEGER DEFAULT (strftime('%s', 'now'))
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS behavior_stats (
                user_id TEXT PRIMARY KEY,
                create_count INTEGER DEFAULT 0,
                update_count INTEGER DEFAULT 0,
                snooze_count INTEGER DEFAULT 0,
                snooze_minutes_total INTEGER DEFAULT 0,
                done_count INTEGER DEFAULT 0,
                complete_minutes_total INTEGER DEFAULT 0,
                last_event_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
            """
        )

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(due_at_epoch)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_convo_user ON conversation_messages(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_convo_created ON conversation_messages(created_at)")

        # Migrate legacy tables
        cursor.execute("PRAGMA table_info(reminders)")
        reminder_cols = [row[1] for row in cursor.fetchall()]
        if "user_id" not in reminder_cols:
            cursor.execute("ALTER TABLE reminders ADD COLUMN user_id TEXT")
        if "mem0_memory_id" not in reminder_cols:
            cursor.execute("ALTER TABLE reminders ADD COLUMN mem0_memory_id TEXT")
        if "last_notified_at" not in reminder_cols:
            cursor.execute("ALTER TABLE reminders ADD COLUMN last_notified_at INTEGER")
        if "reschedule_count" not in reminder_cols:
            cursor.execute("ALTER TABLE reminders ADD COLUMN reschedule_count INTEGER DEFAULT 0")
        if "last_rescheduled_at" not in reminder_cols:
            cursor.execute("ALTER TABLE reminders ADD COLUMN last_rescheduled_at INTEGER")
        if "category" not in reminder_cols:
            cursor.execute("ALTER TABLE reminders ADD COLUMN category TEXT")

        cursor.execute("PRAGMA table_info(preferences)")
        pref_cols = [row[1] for row in cursor.fetchall()]
        if "user_id" not in pref_cols:
            cursor.execute("ALTER TABLE preferences ADD COLUMN user_id TEXT")
        if "mem0_memory_id" not in pref_cols:
            cursor.execute("ALTER TABLE preferences ADD COLUMN mem0_memory_id TEXT")

        cursor.execute("PRAGMA table_info(audit_logs)")
        audit_cols = [row[1] for row in cursor.fetchall()]
        if "timestamp" not in audit_cols:
            cursor.execute("ALTER TABLE audit_logs ADD COLUMN timestamp INTEGER")
        if "user_id" not in audit_cols:
            cursor.execute("ALTER TABLE audit_logs ADD COLUMN user_id TEXT")

        cursor.execute("PRAGMA table_info(conversation_messages)")
        convo_cols = [row[1] for row in cursor.fetchall()]
        if "user_id" not in convo_cols:
            cursor.execute("ALTER TABLE conversation_messages ADD COLUMN user_id TEXT")
        if "role" not in convo_cols:
            cursor.execute("ALTER TABLE conversation_messages ADD COLUMN role TEXT")
        if "content" not in convo_cols:
            cursor.execute("ALTER TABLE conversation_messages ADD COLUMN content TEXT")
        if "created_at" not in convo_cols:
            cursor.execute("ALTER TABLE conversation_messages ADD COLUMN created_at INTEGER")

        cursor.execute("PRAGMA table_info(behavior_stats)")
        behavior_cols = [row[1] for row in cursor.fetchall()]
        if "user_id" not in behavior_cols:
            cursor.execute("ALTER TABLE behavior_stats ADD COLUMN user_id TEXT")
        if "create_count" not in behavior_cols:
            cursor.execute("ALTER TABLE behavior_stats ADD COLUMN create_count INTEGER DEFAULT 0")
        if "update_count" not in behavior_cols:
            cursor.execute("ALTER TABLE behavior_stats ADD COLUMN update_count INTEGER DEFAULT 0")
        if "snooze_count" not in behavior_cols:
            cursor.execute("ALTER TABLE behavior_stats ADD COLUMN snooze_count INTEGER DEFAULT 0")
        if "snooze_minutes_total" not in behavior_cols:
            cursor.execute("ALTER TABLE behavior_stats ADD COLUMN snooze_minutes_total INTEGER DEFAULT 0")
        if "done_count" not in behavior_cols:
            cursor.execute("ALTER TABLE behavior_stats ADD COLUMN done_count INTEGER DEFAULT 0")
        if "complete_minutes_total" not in behavior_cols:
            cursor.execute("ALTER TABLE behavior_stats ADD COLUMN complete_minutes_total INTEGER DEFAULT 0")
        if "last_event_at" not in behavior_cols:
            cursor.execute("ALTER TABLE behavior_stats ADD COLUMN last_event_at INTEGER")

        conn.commit()
        conn.close()

    def _log_audit(self, cursor, user_id: str, action: str, details: str = ""):
        cursor.execute(
            """
            INSERT INTO audit_logs (user_id, action, details, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, action, details, _now_epoch()),
        )

    # === REMINDER OPERATIONS ===

    def create_reminder(
        self,
        user_id: str,
        title: str,
        description: str = "",
        due_at_epoch: int = None,
        category: str = None,
    ) -> int:
        conn = self.get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO reminders (user_id, title, description, due_at_epoch, category)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, title, description, due_at_epoch, category),
        )

        reminder_id = cursor.lastrowid
        self._log_audit(cursor, user_id, "create_reminder", f"Created {reminder_id}: {title}")
        conn.commit()
        conn.close()
        return reminder_id

    def get_reminder(self, reminder_id: int, user_id: str) -> Optional[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id))
        result = cursor.fetchone()
        conn.close()
        return result

    def update_reminder(
        self,
        reminder_id: int,
        user_id: str,
        title: str = None,
        description: str = None,
        due_at_epoch: int = None,
        status: str = None,
        rescheduled: bool = False,
        category: str = None,
    ) -> bool:
        conn = self.get_conn()
        cursor = conn.cursor()

        updates = []
        params = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if due_at_epoch is not None:
            updates.append("due_at_epoch = ?")
            params.append(due_at_epoch)
            updates.append("last_notified_at = NULL")
        if category is not None:
            updates.append("category = ?")
            params.append(category)
        if rescheduled:
            updates.append("reschedule_count = reschedule_count + 1")
            updates.append("last_rescheduled_at = ?")
            params.append(_now_epoch())
        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if not updates:
            conn.close()
            return False

        updates.append("updated_at = ?")
        params.append(_now_epoch())
        params.extend([reminder_id, user_id])

        query = f"UPDATE reminders SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
        cursor.execute(query, params)
        self._log_audit(cursor, user_id, "update_reminder", f"Updated {reminder_id}: {', '.join(updates)}")
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def mark_reminder_done(self, reminder_id: int, user_id: str) -> bool:
        return self.update_reminder(reminder_id, user_id, status="completed")

    def delete_reminder(self, reminder_id: int, user_id: str) -> bool:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id))
        self._log_audit(cursor, user_id, "delete_reminder", f"Deleted {reminder_id}")
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def list_active_reminders(self, user_id: str) -> List[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM reminders
            WHERE user_id = ? AND status = 'active'
            ORDER BY due_at_epoch ASC
            """,
            (user_id,),
        )
        results = cursor.fetchall()
        conn.close()
        return results

    def list_rescheduled_reminders(self, user_id: str) -> List[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM reminders
            WHERE user_id = ? AND status = 'active' AND reschedule_count > 0
            ORDER BY last_rescheduled_at DESC
            """,
            (user_id,),
        )
        results = cursor.fetchall()
        conn.close()
        return results

    def list_reminder_times_by_category(self, user_id: str) -> List[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT category, due_at_epoch
            FROM reminders
            WHERE user_id = ? AND category IS NOT NULL AND due_at_epoch IS NOT NULL
            """,
            (user_id,),
        )
        results = cursor.fetchall()
        conn.close()
        return results

    def list_completed_reminders(self, user_id: str) -> List[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM reminders
            WHERE user_id = ? AND status = 'completed'
            ORDER BY updated_at DESC
            """,
            (user_id,),
        )
        results = cursor.fetchall()
        conn.close()
        return results

    def list_all_reminders(self, user_id: str) -> List[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reminders WHERE user_id = ? ORDER BY due_at_epoch ASC", (user_id,))
        results = cursor.fetchall()
        conn.close()
        return results

    def search_reminders(self, user_id: str, query: str) -> List[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        search_term = f"%{query}%"
        cursor.execute(
            """
            SELECT * FROM reminders
            WHERE user_id = ? AND (title LIKE ? OR description LIKE ?)
            ORDER BY due_at_epoch ASC
            """,
            (user_id, search_term, search_term),
        )
        results = cursor.fetchall()
        conn.close()
        return results

    def update_reminder_mem0_id(self, reminder_id: int, user_id: str, mem0_id: str):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE reminders
            SET mem0_memory_id = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (mem0_id, _now_epoch(), reminder_id, user_id),
        )
        conn.commit()
        conn.close()

    def get_due_soon_reminders(
        self,
        user_id: str,
        now_epoch: int,
        lead_time_seconds: int = 600,
    ) -> List[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        window_end = now_epoch + lead_time_seconds
        cursor.execute(
            """
            SELECT * FROM reminders
            WHERE user_id = ?
              AND status = 'active'
              AND due_at_epoch >= ?
              AND due_at_epoch <= ?
              AND (last_notified_at IS NULL OR last_notified_at < due_at_epoch - ?)
            ORDER BY due_at_epoch ASC
            """,
            (user_id, now_epoch, window_end, lead_time_seconds),
        )
        results = cursor.fetchall()
        conn.close()
        return results

    def mark_reminder_notified(self, reminder_id: int, user_id: str, notified_at: int):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE reminders
            SET last_notified_at = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (notified_at, _now_epoch(), reminder_id, user_id),
        )
        self._log_audit(cursor, user_id, "reminder_notified", f"Notified {reminder_id}")
        conn.commit()
        conn.close()

    # === PREFERENCE OPERATIONS ===

    def set_preference(self, user_id: str, key: str, value: str):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO preferences (user_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (user_id, key, value, _now_epoch()),
        )
        self._log_audit(cursor, user_id, "set_preference", f"Set {key} = {value}")
        conn.commit()
        conn.close()

    def get_preference(self, user_id: str, key: str) -> Optional[str]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM preferences WHERE user_id = ? AND key = ?", (user_id, key))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    def get_all_preferences(self, user_id: str) -> List[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM preferences WHERE user_id = ?", (user_id,))
        results = cursor.fetchall()
        conn.close()
        return results

    def update_preference_mem0_id(self, user_id: str, key: str, mem0_id: str):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE preferences
            SET mem0_memory_id = ?, updated_at = ?
            WHERE user_id = ? AND key = ?
            """,
            (mem0_id, _now_epoch(), user_id, key),
        )
        conn.commit()
        conn.close()

    # === AUDIT LOG ===

    def log_audit(self, user_id: str, action: str, details: str = ""):
        conn = self.get_conn()
        cursor = conn.cursor()
        self._log_audit(cursor, user_id, action, details)
        conn.commit()
        conn.close()

    def get_recent_audit_logs(self, user_id: str, limit: int = 50) -> List[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM audit_logs
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        results = cursor.fetchall()
        conn.close()
        return results

    def add_conversation_message(self, user_id: str, role: str, content: str):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO conversation_messages (user_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, role, content, _now_epoch()),
        )
        conn.commit()
        conn.close()

    def get_recent_conversation(self, user_id: str, limit: int = 6) -> List[sqlite3.Row]:
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content, created_at
            FROM conversation_messages
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        results = cursor.fetchall()
        conn.close()
        return list(reversed(results))

    def _ensure_behavior_row(self, cursor, user_id: str):
        cursor.execute(
            """
            INSERT OR IGNORE INTO behavior_stats (user_id)
            VALUES (?)
            """,
            (user_id,),
        )

    def record_behavior_create(self, user_id: str):
        conn = self.get_conn()
        cursor = conn.cursor()
        self._ensure_behavior_row(cursor, user_id)
        cursor.execute(
            """
            UPDATE behavior_stats
            SET create_count = create_count + 1,
                last_event_at = ?
            WHERE user_id = ?
            """,
            (_now_epoch(), user_id),
        )
        conn.commit()
        conn.close()

    def record_behavior_update(self, user_id: str):
        conn = self.get_conn()
        cursor = conn.cursor()
        self._ensure_behavior_row(cursor, user_id)
        cursor.execute(
            """
            UPDATE behavior_stats
            SET update_count = update_count + 1,
                last_event_at = ?
            WHERE user_id = ?
            """,
            (_now_epoch(), user_id),
        )
        conn.commit()
        conn.close()

    def record_behavior_snooze(self, user_id: str, minutes: int):
        conn = self.get_conn()
        cursor = conn.cursor()
        self._ensure_behavior_row(cursor, user_id)
        cursor.execute(
            """
            UPDATE behavior_stats
            SET snooze_count = snooze_count + 1,
                snooze_minutes_total = snooze_minutes_total + ?,
                last_event_at = ?
            WHERE user_id = ?
            """,
            (minutes, _now_epoch(), user_id),
        )
        conn.commit()
        conn.close()

    def record_behavior_done(self, user_id: str, minutes: int):
        conn = self.get_conn()
        cursor = conn.cursor()
        self._ensure_behavior_row(cursor, user_id)
        cursor.execute(
            """
            UPDATE behavior_stats
            SET done_count = done_count + 1,
                complete_minutes_total = complete_minutes_total + ?,
                last_event_at = ?
            WHERE user_id = ?
            """,
            (minutes, _now_epoch(), user_id),
        )
        conn.commit()
        conn.close()

    def get_behavior_stats(self, user_id: str) -> dict:
        conn = self.get_conn()
        cursor = conn.cursor()
        self._ensure_behavior_row(cursor, user_id)
        cursor.execute(
            """
            SELECT create_count, update_count, snooze_count, snooze_minutes_total,
                   done_count, complete_minutes_total, last_event_at
            FROM behavior_stats
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        conn.commit()
        conn.close()
        if not row:
            return {
                "create_count": 0,
                "update_count": 0,
                "snooze_count": 0,
                "snooze_minutes_total": 0,
                "done_count": 0,
                "complete_minutes_total": 0,
                "last_event_at": None,
                "avg_snooze_minutes": 0,
                "avg_complete_minutes": 0,
            }
        snooze_count = row[2] or 0
        snooze_total = row[3] or 0
        done_count = row[4] or 0
        complete_total = row[5] or 0
        avg_snooze = round(snooze_total / snooze_count, 1) if snooze_count else 0
        avg_complete = round(complete_total / done_count, 1) if done_count else 0
        return {
            "create_count": row[0] or 0,
            "update_count": row[1] or 0,
            "snooze_count": snooze_count,
            "snooze_minutes_total": snooze_total,
            "done_count": done_count,
            "complete_minutes_total": complete_total,
            "last_event_at": row[6],
            "avg_snooze_minutes": avg_snooze,
            "avg_complete_minutes": avg_complete,
        }


class SupabaseDatabase:
    """Supabase-backed database for production and multi-instance use."""

    def __init__(self, url: str, key: str):
        if not create_client:
            raise RuntimeError("supabase client is not installed (pip install supabase)")
        self.client = create_client(url, key)

    def _response_data(self, response) -> Optional[List[Dict[str, Any]]]:
        error = getattr(response, "error", None)
        if error:
            print(f"Supabase error: {error}")
            return None
        return getattr(response, "data", None)

    def _select_one(self, table: str, filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        query = self.client.table(table).select("*")
        for key, value in filters.items():
            query = query.eq(key, value)
        response = query.limit(1).execute()
        data = self._response_data(response) or []
        return data[0] if data else None

    def _ensure_behavior_row(self, user_id: str):
        payload = {
            "user_id": user_id,
            "create_count": 0,
            "update_count": 0,
            "snooze_count": 0,
            "snooze_minutes_total": 0,
            "done_count": 0,
            "complete_minutes_total": 0,
            "last_event_at": _now_epoch(),
        }
        self.client.table("behavior_stats").upsert(payload, on_conflict="user_id").execute()

    # === REMINDER OPERATIONS ===

    def create_reminder(
        self,
        user_id: str,
        title: str,
        description: str = "",
        due_at_epoch: int = None,
        category: str = None,
    ) -> Optional[int]:
        payload = {
            "user_id": user_id,
            "title": title,
            "description": description or "",
            "due_at_epoch": due_at_epoch,
            "status": "active",
            "category": category,
            "created_at": _now_epoch(),
            "updated_at": _now_epoch(),
        }
        response = self.client.table("reminders").insert(payload).execute()
        data = self._response_data(response) or []
        if not data:
            return None
        return data[0].get("id")

    def get_reminder(self, reminder_id: int, user_id: str) -> Optional[Dict[str, Any]]:
        return self._select_one("reminders", {"id": reminder_id, "user_id": user_id})

    def update_reminder(
        self,
        reminder_id: int,
        user_id: str,
        title: str = None,
        description: str = None,
        due_at_epoch: int = None,
        status: str = None,
        rescheduled: bool = False,
        category: str = None,
    ) -> bool:
        updates: Dict[str, Any] = {}
        if title is not None:
            updates["title"] = title
        if description is not None:
            updates["description"] = description
        if due_at_epoch is not None:
            updates["due_at_epoch"] = due_at_epoch
            updates["last_notified_at"] = None
        if category is not None:
            updates["category"] = category
        if rescheduled:
            existing = self.get_reminder(reminder_id, user_id) or {}
            current = existing.get("reschedule_count") or 0
            updates["reschedule_count"] = current + 1
            updates["last_rescheduled_at"] = _now_epoch()
        if status is not None:
            updates["status"] = status
        if not updates:
            return False
        updates["updated_at"] = _now_epoch()
        response = (
            self.client.table("reminders")
            .update(updates)
            .eq("id", reminder_id)
            .eq("user_id", user_id)
            .execute()
        )
        data = self._response_data(response) or []
        return bool(data)

    def mark_reminder_done(self, reminder_id: int, user_id: str) -> bool:
        return self.update_reminder(reminder_id, user_id, status="completed")

    def delete_reminder(self, reminder_id: int, user_id: str) -> bool:
        response = (
            self.client.table("reminders")
            .delete()
            .eq("id", reminder_id)
            .eq("user_id", user_id)
            .execute()
        )
        data = self._response_data(response) or []
        return bool(data)

    def list_active_reminders(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table("reminders")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "active")
            .order("due_at_epoch", desc=False)
            .execute()
        )
        return self._response_data(response) or []

    def list_rescheduled_reminders(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table("reminders")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "active")
            .gt("reschedule_count", 0)
            .order("last_rescheduled_at", desc=True)
            .execute()
        )
        return self._response_data(response) or []

    def list_reminder_times_by_category(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table("reminders")
            .select("category,due_at_epoch")
            .eq("user_id", user_id)
            .execute()
        )
        data = self._response_data(response) or []
        return [row for row in data if row.get("category") is not None and row.get("due_at_epoch") is not None]

    def list_completed_reminders(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table("reminders")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .order("updated_at", desc=True)
            .execute()
        )
        return self._response_data(response) or []

    def list_all_reminders(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table("reminders")
            .select("*")
            .eq("user_id", user_id)
            .order("due_at_epoch", desc=False)
            .execute()
        )
        return self._response_data(response) or []

    def search_reminders(self, user_id: str, query: str) -> List[Dict[str, Any]]:
        search_term = f"%{query}%"
        response = (
            self.client.table("reminders")
            .select("*")
            .eq("user_id", user_id)
            .or_(f"title.ilike.{search_term},description.ilike.{search_term}")
            .order("due_at_epoch", desc=False)
            .execute()
        )
        return self._response_data(response) or []

    def update_reminder_mem0_id(self, reminder_id: int, user_id: str, mem0_id: str):
        (
            self.client.table("reminders")
            .update({"mem0_memory_id": mem0_id, "updated_at": _now_epoch()})
            .eq("id", reminder_id)
            .eq("user_id", user_id)
            .execute()
        )

    def get_due_soon_reminders(
        self,
        user_id: str,
        now_epoch: int,
        lead_time_seconds: int = 600,
    ) -> List[Dict[str, Any]]:
        window_end = now_epoch + lead_time_seconds
        response = (
            self.client.table("reminders")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "active")
            .gte("due_at_epoch", now_epoch)
            .lte("due_at_epoch", window_end)
            .order("due_at_epoch", desc=False)
            .execute()
        )
        data = self._response_data(response) or []
        cutoff = now_epoch + lead_time_seconds
        filtered = []
        for row in data:
            last_notified = row.get("last_notified_at")
            due_at = row.get("due_at_epoch")
            if due_at is None:
                continue
            if last_notified is None or last_notified < due_at - lead_time_seconds:
                if due_at <= cutoff:
                    filtered.append(row)
        return filtered

    def mark_reminder_notified(self, reminder_id: int, user_id: str, notified_at: int):
        (
            self.client.table("reminders")
            .update({"last_notified_at": notified_at, "updated_at": _now_epoch()})
            .eq("id", reminder_id)
            .eq("user_id", user_id)
            .execute()
        )

    # === PREFERENCE OPERATIONS ===

    def set_preference(self, user_id: str, key: str, value: str):
        payload = {
            "user_id": user_id,
            "key": key,
            "value": value,
            "updated_at": _now_epoch(),
        }
        self.client.table("preferences").upsert(payload, on_conflict="user_id,key").execute()

    def get_preference(self, user_id: str, key: str) -> Optional[str]:
        row = self._select_one("preferences", {"user_id": user_id, "key": key})
        if not row:
            return None
        return row.get("value")

    def get_all_preferences(self, user_id: str) -> List[Dict[str, Any]]:
        response = (
            self.client.table("preferences")
            .select("key,value")
            .eq("user_id", user_id)
            .execute()
        )
        return self._response_data(response) or []

    def update_preference_mem0_id(self, user_id: str, key: str, mem0_id: str):
        (
            self.client.table("preferences")
            .update({"mem0_memory_id": mem0_id, "updated_at": _now_epoch()})
            .eq("user_id", user_id)
            .eq("key", key)
            .execute()
        )

    # === AUDIT LOG ===

    def log_audit(self, user_id: str, action: str, details: str = ""):
        payload = {
            "user_id": user_id,
            "action": action,
            "details": details,
            "timestamp": _now_epoch(),
        }
        self.client.table("audit_logs").insert(payload).execute()

    def get_recent_audit_logs(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        response = (
            self.client.table("audit_logs")
            .select("*")
            .eq("user_id", user_id)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return self._response_data(response) or []

    def add_conversation_message(self, user_id: str, role: str, content: str):
        payload = {
            "user_id": user_id,
            "role": role,
            "content": content,
            "created_at": _now_epoch(),
        }
        self.client.table("conversation_messages").insert(payload).execute()

    def get_recent_conversation(self, user_id: str, limit: int = 6) -> List[Dict[str, Any]]:
        response = (
            self.client.table("conversation_messages")
            .select("role,content,created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        data = self._response_data(response) or []
        return list(reversed(data))

    # === BEHAVIOR STATS ===

    def record_behavior_create(self, user_id: str):
        self._ensure_behavior_row(user_id)
        row = self._select_one("behavior_stats", {"user_id": user_id}) or {}
        payload = {
            "user_id": user_id,
            "create_count": (row.get("create_count") or 0) + 1,
            "update_count": row.get("update_count") or 0,
            "snooze_count": row.get("snooze_count") or 0,
            "snooze_minutes_total": row.get("snooze_minutes_total") or 0,
            "done_count": row.get("done_count") or 0,
            "complete_minutes_total": row.get("complete_minutes_total") or 0,
            "last_event_at": _now_epoch(),
        }
        self.client.table("behavior_stats").upsert(payload, on_conflict="user_id").execute()

    def record_behavior_update(self, user_id: str):
        self._ensure_behavior_row(user_id)
        row = self._select_one("behavior_stats", {"user_id": user_id}) or {}
        payload = {
            "user_id": user_id,
            "create_count": row.get("create_count") or 0,
            "update_count": (row.get("update_count") or 0) + 1,
            "snooze_count": row.get("snooze_count") or 0,
            "snooze_minutes_total": row.get("snooze_minutes_total") or 0,
            "done_count": row.get("done_count") or 0,
            "complete_minutes_total": row.get("complete_minutes_total") or 0,
            "last_event_at": _now_epoch(),
        }
        self.client.table("behavior_stats").upsert(payload, on_conflict="user_id").execute()

    def record_behavior_snooze(self, user_id: str, minutes: int):
        self._ensure_behavior_row(user_id)
        row = self._select_one("behavior_stats", {"user_id": user_id}) or {}
        payload = {
            "user_id": user_id,
            "create_count": row.get("create_count") or 0,
            "update_count": row.get("update_count") or 0,
            "snooze_count": (row.get("snooze_count") or 0) + 1,
            "snooze_minutes_total": (row.get("snooze_minutes_total") or 0) + minutes,
            "done_count": row.get("done_count") or 0,
            "complete_minutes_total": row.get("complete_minutes_total") or 0,
            "last_event_at": _now_epoch(),
        }
        self.client.table("behavior_stats").upsert(payload, on_conflict="user_id").execute()

    def record_behavior_done(self, user_id: str, minutes: int):
        self._ensure_behavior_row(user_id)
        row = self._select_one("behavior_stats", {"user_id": user_id}) or {}
        payload = {
            "user_id": user_id,
            "create_count": row.get("create_count") or 0,
            "update_count": row.get("update_count") or 0,
            "snooze_count": row.get("snooze_count") or 0,
            "snooze_minutes_total": row.get("snooze_minutes_total") or 0,
            "done_count": (row.get("done_count") or 0) + 1,
            "complete_minutes_total": (row.get("complete_minutes_total") or 0) + minutes,
            "last_event_at": _now_epoch(),
        }
        self.client.table("behavior_stats").upsert(payload, on_conflict="user_id").execute()

    def get_behavior_stats(self, user_id: str) -> dict:
        row = self._select_one("behavior_stats", {"user_id": user_id})
        if not row:
            self._ensure_behavior_row(user_id)
            row = self._select_one("behavior_stats", {"user_id": user_id}) or {}
        snooze_count = row.get("snooze_count") or 0
        snooze_total = row.get("snooze_minutes_total") or 0
        done_count = row.get("done_count") or 0
        complete_total = row.get("complete_minutes_total") or 0
        avg_snooze = round(snooze_total / snooze_count, 1) if snooze_count else 0
        avg_complete = round(complete_total / done_count, 1) if done_count else 0
        return {
            "create_count": row.get("create_count") or 0,
            "update_count": row.get("update_count") or 0,
            "snooze_count": snooze_count,
            "snooze_minutes_total": snooze_total,
            "done_count": done_count,
            "complete_minutes_total": complete_total,
            "last_event_at": row.get("last_event_at"),
            "avg_snooze_minutes": avg_snooze,
            "avg_complete_minutes": avg_complete,
        }


class Database:
    """Select Supabase when configured, otherwise fallback to SQLite."""

    def __init__(self, db_path: str = "data.db"):
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_KEY", "").strip()
        if url and key:
            self.backend = SupabaseDatabase(url, key)
        else:
            self.backend = SQLiteDatabase(db_path)

    def __getattr__(self, name: str):
        return getattr(self.backend, name)
