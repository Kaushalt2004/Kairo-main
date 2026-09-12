import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class OfflineQueue:
    """SQLite-backed persistent queue for buffering telemetry when network connectivity is lost."""

    def __init__(self, db_path: str = "kairo_offline_queue.db", max_size: int = 50000):
        self.db_path = db_path
        self.max_size = max_size
        self._init_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS telemetry_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        payload TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS ix_queue_id ON telemetry_queue(id ASC);")
                conn.commit()
        except Exception as e:
            logger.error("Failed to initialize offline queue DB: %s", e)

    def enqueue(self, payload: Dict[str, Any]) -> bool:
        """Stores a telemetry packet in the local database."""
        try:
            payload_str = json.dumps(payload)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("INSERT INTO telemetry_queue (payload) VALUES (?);", (payload_str,))
                conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to enqueue telemetry to offline buffer: %s", e)
            return False

    def peek_batch(self, limit: int = 50) -> List[Tuple[int, Dict[str, Any]]]:
        """Retrieves the oldest queued records without deleting them."""
        results = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, payload FROM telemetry_queue ORDER BY id ASC LIMIT ?;", (limit,))
                rows = cursor.fetchall()
                for row_id, payload_str in rows:
                    results.append((row_id, json.loads(payload_str)))
        except Exception as e:
            logger.error("Failed to read from offline queue: %s", e)
        return results

    def delete_batch(self, ids: List[int]) -> None:
        """Deletes acknowledged records from the queue."""
        if not ids:
            return
        try:
            placeholders = ",".join("?" for _ in ids)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(f"DELETE FROM telemetry_queue WHERE id IN ({placeholders});", ids)
                conn.commit()
        except Exception as e:
            logger.error("Failed to delete records from offline queue: %s", e)

    def count(self) -> int:
        """Returns the number of buffered packets."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM telemetry_queue;")
                return cursor.fetchone()[0]
        except Exception:
            return 0
