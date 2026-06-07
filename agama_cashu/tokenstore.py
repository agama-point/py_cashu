from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable


class TokenStore:
    def __init__(
        self,
        path: Path,
        token_txt_path: Path,
        token_png_path: Path,
        *,
        now_fn: Callable[[], str],
    ) -> None:
        self.path = path
        self.token_txt_path = token_txt_path
        self.token_png_path = token_png_path
        self._now = now_fn
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    mint_label TEXT NOT NULL,
                    mint_url TEXT NOT NULL,
                    amount INTEGER,
                    label TEXT NOT NULL,
                    token_text TEXT NOT NULL,
                    token_txt_path TEXT NOT NULL,
                    token_png_path TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    is_mock INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {
                row[1]
                for row in conn.execute('PRAGMA table_info("tokens")').fetchall()
            }
            if "mint_label" not in columns:
                conn.execute('ALTER TABLE tokens ADD COLUMN mint_label TEXT NOT NULL DEFAULT "?"')
            if "mint_url" not in columns:
                conn.execute('ALTER TABLE tokens ADD COLUMN mint_url TEXT NOT NULL DEFAULT ""')

    def insert(
        self,
        *,
        mint: Any,
        amount: int | None,
        label: str,
        token: str,
        is_mock: bool,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO tokens (
                    created_at, mint_label, mint_url, amount, label, token_text,
                    token_txt_path, token_png_path, used, is_mock
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    self._now(),
                    mint.label,
                    mint.url,
                    amount,
                    label,
                    token,
                    str(self.token_txt_path),
                    str(self.token_png_path),
                    1 if is_mock else 0,
                ),
            )
            return int(cur.lastrowid)

    def last(self, limit: int = 5, *, include_used: bool = False) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            where = "" if include_used else "WHERE used = 0"
            rows = conn.execute(
                f"""
                SELECT id, created_at, COALESCE(mint_label, '?') AS mint_label,
                       amount, label, used, is_mock
                FROM tokens
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, token_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, created_at, COALESCE(mint_label, '?') AS mint_label,
                       COALESCE(mint_url, '') AS mint_url, amount, label,
                       token_text, token_txt_path, token_png_path, used, is_mock
                FROM tokens
                WHERE id = ?
                """,
                (token_id,),
            ).fetchone()
        return dict(row) if row else None

    def toggle(self, token_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tokens SET used = CASE used WHEN 0 THEN 1 ELSE 0 END WHERE id = ?",
                (token_id,),
            )

    def mark_used_by_token(self, token: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE tokens SET used = 1 WHERE token_text = ? AND used = 0",
                (token,),
            )
            return int(cur.rowcount)

    def delete(self, token_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tokens WHERE id = ?", (token_id,))
