import logging
import sqlite3
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
DB_PATH = "bot_stats.db"


def init_db() -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT,
                timestamp TEXT,
                ip TEXT,
                status INTEGER,
                request_id TEXT,
                paid BOOLEAN DEFAULT 0
            )"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS rate_limit (
                ip TEXT PRIMARY KEY,
                count INTEGER,
                reset_at TEXT
            )"""
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("Database init failed: %s", exc)


def log_request(query: str, ip: str, status: int, request_id: str = "", paid: bool = False) -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO requests (query, timestamp, ip, status, request_id, paid) VALUES (?, ?, ?, ?, ?, ?)",
            (query, datetime.utcnow().isoformat(), ip, status, request_id, 1 if paid else 0),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("Failed to log request: %s", exc)


def check_rate_limit(ip: str, limit: int) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now = datetime.utcnow()
        reset_at = now + timedelta(minutes=1)

        cursor.execute("SELECT count, reset_at FROM rate_limit WHERE ip = ?", (ip,))
        row = cursor.fetchone()

        if row:
            count, reset_at_str = row
            reset_at_db = datetime.fromisoformat(reset_at_str)
            if now > reset_at_db:
                cursor.execute(
                    "UPDATE rate_limit SET count = 1, reset_at = ? WHERE ip = ?",
                    (reset_at.isoformat(), ip),
                )
            elif count >= limit:
                conn.commit()
                conn.close()
                return False
            else:
                cursor.execute("UPDATE rate_limit SET count = count + 1 WHERE ip = ?", (ip,))
        else:
            cursor.execute(
                "INSERT INTO rate_limit (ip, count, reset_at) VALUES (?, ?, ?)",
                (ip, 1, reset_at.isoformat()),
            )

        conn.commit()
        conn.close()
        return True
    except Exception as exc:
        logger.error("Rate limit check failed: %s", exc)
        return True


def get_stats() -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM requests")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM requests WHERE paid = 1")
        paid = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM requests WHERE timestamp >= datetime('now', '-1 day')"
        )
        last_24h = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM requests WHERE paid = 1 AND timestamp >= datetime('now', '-1 day')"
        )
        paid_24h = cursor.fetchone()[0]
        cursor.execute(
            "SELECT query, COUNT(*) AS c FROM requests GROUP BY query ORDER BY c DESC LIMIT 5"
        )
        top_queries = [{"query": row[0], "count": row[1]} for row in cursor.fetchall()]
        conn.close()
        freeish = max(0, total - paid)
        conversion_pct = round((paid / total) * 100, 2) if total else 0.0
        return {
            "total_requests": total,
            "paid_requests": paid,
            "free_requests": freeish,
            "requests_24h": last_24h,
            "paid_24h": paid_24h,
            "conversion_pct": conversion_pct,
            "top_queries": top_queries,
        }
    except Exception:
        return {
            "total_requests": 0,
            "paid_requests": 0,
            "free_requests": 0,
            "requests_24h": 0,
            "paid_24h": 0,
            "conversion_pct": 0.0,
            "top_queries": [],
        }
