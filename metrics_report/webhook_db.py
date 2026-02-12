from __future__ import annotations

import sqlite3


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_counts (
            date TEXT NOT NULL,
            metric TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (date, metric)
        );
        CREATE TABLE IF NOT EXISTS seen_carts (
            cart_token TEXT PRIMARY KEY,
            date TEXT NOT NULL
        );
    """)


def increment(db_path: str, date: str, metric: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        _ensure_tables(conn)
        conn.execute(
            "INSERT INTO daily_counts (date, metric, count) VALUES (?, ?, 1) "
            "ON CONFLICT(date, metric) DO UPDATE SET count = count + 1",
            (date, metric),
        )
        conn.commit()
    finally:
        conn.close()


def try_record_cart(db_path: str, cart_token: str, date: str) -> bool:
    """Record a cart token. Returns True if the cart is new (not seen before)."""
    conn = sqlite3.connect(db_path)
    try:
        _ensure_tables(conn)
        try:
            conn.execute(
                "INSERT INTO seen_carts (cart_token, date) VALUES (?, ?)",
                (cart_token, date),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    finally:
        conn.close()


def get_counts(db_path: str, start_date: str, end_date: str) -> list[dict[str, str | int]]:
    conn = sqlite3.connect(db_path)
    try:
        _ensure_tables(conn)
        rows = conn.execute(
            "SELECT date, metric, count FROM daily_counts "
            "WHERE date >= ? AND date <= ? ORDER BY date",
            (start_date, end_date),
        ).fetchall()
        return [{"date": r[0], "metric": r[1], "count": r[2]} for r in rows]
    finally:
        conn.close()


def cleanup_old_carts(db_path: str, before_date: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        _ensure_tables(conn)
        cursor = conn.execute("DELETE FROM seen_carts WHERE date < ?", (before_date,))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
