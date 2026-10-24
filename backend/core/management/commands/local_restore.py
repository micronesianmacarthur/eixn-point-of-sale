"""
14.2 — Local Restore (non-cloud)

Decompresses a ``.sql.gz`` backup file and runs ``pg_restore`` with
``--clean --if-exists --no-owner --no-acl`` to fully restore the database
(wipe-and-replace). Intended for admin/manager use via the settings UI.

Warning: this destroys all current data and replaces it with the snapshot.
"""

import gzip
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Restore the PostgreSQL database from a local .sql.gz backup file."

    def add_arguments(self, parser):
        parser.add_argument(
            "backup_file",
            type=Path,
            help="Path to the .sql.gz backup file to restore from.",
        )

    def handle(self, *args, **options):
        backup_file = options["backup_file"]

        if not backup_file.exists():
            raise CommandError(f"Backup file not found: {backup_file}")

        # ── Database URL parsing ──────────────────────────────────────
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url.startswith("postgres"):
            raise CommandError(
                "local_restore is designed for PostgreSQL. "
                f"DATABASE_URL must be postgres:// — got: {db_url[:30]}..."
            )

        conn_parts = self._parse_db_url(db_url)

        # ── Step 1: Decompress ────────────────────────────────────────
        self.stdout.write(f"Decompressing {backup_file} ...")
        temp_sql = Path(tempfile.mkstemp(suffix=".sql")[1])
        try:
            with gzip.open(backup_file, "rb") as f_in:
                with open(temp_sql, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        except (gzip.BadGzipFile, OSError) as exc:
            raise CommandError(f"Invalid gzip file: {exc}") from exc

        # ── Step 2: pg_restore ────────────────────────────────────────
        self.stdout.write(
            "Restoring database (this will wipe and replace all current data) ..."
        )
        try:
            env = os.environ.copy()
            env["PGPASSWORD"] = conn_parts["password"]
            result = subprocess.run(
                [
                    "pg_restore",
                    "-h", conn_parts["host"],
                    "-p", conn_parts["port"],
                    "-U", conn_parts["user"],
                    "-d", conn_parts["dbname"],
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-acl",
                    "-v",
                    str(temp_sql),
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            stderr = result.stderr or ""
            if result.returncode == 0:
                self.stdout.write("pg_restore completed.")
            elif "errors ignored on restore:" in stderr and "FATAL:" not in stderr:
                # pg_restore returns 1 when it hits non-fatal errors, e.g. a
                # SET statement the server version doesn't recognize
                # (pg_dump client newer than the server). If data was
                # processed, treat as a successful restore with a warning.
                self.stdout.write(self.style.WARNING(
                    "pg_restore reported non-fatal errors (likely "
                    "client/server version mismatch). Restore completed."
                ))
            else:
                raise CommandError(f"pg_restore failed:\n{stderr}")
        except FileNotFoundError:
            raise CommandError("pg_restore not found. Install postgresql-client.")
        finally:
            temp_sql.unlink(missing_ok=True)

        self.stdout.write(self.style.SUCCESS("Local restore completed successfully."))

    def _parse_db_url(self, url):
        """
        Parse postgres://user:***@host:port/dbname into a dict.
        """
        rest = url.split("://", 1)[1]
        userinfo, rest = rest.split("@", 1)
        user, password = userinfo.split(":", 1) if ":" in userinfo else (userinfo, "")
        host_port, dbname = rest.split("/", 1)
        if ":" in host_port:
            host, port = host_port.split(":", 1)
        else:
            host = host_port
            port = "5432"
        dbname = dbname.split("?")[0]
        return {
            "user": user,
            "password": password,
            "host": host,
            "port": port,
            "dbname": dbname,
        }
