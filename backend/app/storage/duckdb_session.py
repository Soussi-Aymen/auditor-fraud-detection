from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from app.parsing.documents import DocumentChunk


class DuckDBSession:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(db_path))

    def close(self) -> None:
        self.conn.close()

    def register_dataframe(self, name: str, df: pd.DataFrame) -> None:
        self.conn.register(f"_tmp_{name}", df)
        self.conn.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM "_tmp_{name}"')
        self.conn.unregister(f"_tmp_{name}")

    def store_documents(self, chunks: list[DocumentChunk]) -> None:
        if not chunks:
            self.conn.execute(
                """
                CREATE OR REPLACE TABLE doc_chunks (
                    source_path VARCHAR,
                    locator VARCHAR,
                    text VARCHAR
                )
                """
            )
            return
        df = pd.DataFrame(
            [
                {
                    "source_path": c.source_path,
                    "locator": c.locator,
                    "text": c.text,
                }
                for c in chunks
            ]
        )
        self.register_dataframe("doc_chunks", df)

    def table_row_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_name
            """
        ).fetchall()
        counts: dict[str, int] = {}
        for (name,) in rows:
            n = self.conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
            counts[str(name)] = int(n[0]) if n else 0
        return counts
