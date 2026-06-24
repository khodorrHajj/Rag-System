from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.core.database import build_database_url

MIGRATION_TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    filename text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT timezone('utc', now())
)
"""

def apply_migrations() -> None:
    settings = get_settings()
    repository_root = Path(__file__).resolve().parents[3]
    migration_dir = repository_root / "database" / "migrations"

    migration_files = sorted(migration_dir.glob("*.sql"))
    if not migration_files:
        print("No migration files were found.")
        return

    with psycopg.connect(build_database_url(settings), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(MIGRATION_TRACKING_TABLE_SQL)
            cursor.execute("SELECT filename FROM public.schema_migrations ORDER BY filename ASC")
            applied_files = {row["filename"] for row in cursor.fetchall()}
            applied_count = 0

            if not applied_files:
                cursor.execute("SELECT to_regclass('public.documents') IS NOT NULL AS has_documents_table")
                has_existing_schema = bool(cursor.fetchone()["has_documents_table"])
                if has_existing_schema:
                    print("Existing schema detected. Baselining current migration files as already applied.")
                    for migration_file in migration_files:
                        cursor.execute(
                            """
                            INSERT INTO public.schema_migrations (filename)
                            VALUES (%s)
                            ON CONFLICT (filename) DO NOTHING
                            """,
                            (migration_file.name,),
                        )
                    connection.commit()
                    print(f"Baselined {len(migration_files)} migration files.")
                    return

            for migration_file in migration_files:
                if migration_file.name in applied_files:
                    print(f"Skipping {migration_file.name}; already recorded.")
                    continue

                print(f"Applying {migration_file.name}...")
                cursor.execute(migration_file.read_text(encoding="utf-8"))
                cursor.execute(
                    """
                    INSERT INTO public.schema_migrations (filename)
                    VALUES (%s)
                    ON CONFLICT (filename) DO NOTHING
                    """,
                    (migration_file.name,),
                )
                connection.commit()
                applied_count += 1

    print(f"Applied {applied_count} migration files.")

if __name__ == "__main__":
    apply_migrations()
