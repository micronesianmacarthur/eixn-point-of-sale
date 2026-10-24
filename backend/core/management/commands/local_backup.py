"""
14.1 — Local Backup (non-cloud)

Dumps the PostgreSQL database via pg_dump, compresses with gzip, and writes the
``.sql.gz`` snapshot to ``backend/backups/``. Writes the ``last_backup.txt``
marker so the dashboard widget can report status. No S3 upload — this is a
local-only snapshot for admin/manager restore.
"""

import gzip
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Dump the PostgreSQL database to a compressed local .sql.gz backup."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=Path,
            help="Destination path for the backup file (defaults to backend/backups/).",
        )
        parser.add_argument(
            "--keep-local",
            action="store_true",
            help="Keep the local compressed dump file (default: kept for local restore).",
        )

    def handle(self, *args, **options):
        output = options["output"]

        # ── Database URL parsing ──────────────────────────────────────
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url.startswith("postgres"):
            raise CommandError(
                "local_backup is designed for PostgreSQL. "
                f"DATABASE_URL must be postgres:// — got: {db_url[:30]}..."
            )

        conn_parts = self._parse_db_url(db_url)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dump_filename = f"eixn_pos_{timestamp}.sql.gz"
        # -Fc = custom archive format (compressible, restorable with pg_restore).
        # Plain-text dumps cannot be restored by pg_restore.

        if output is None:
            backup_dir = Path(settings.BASE_DIR) / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            dump_path = backup_dir / dump_filename
        else:
            dump_path = Path(output)
            dump_path.parent.mkdir(parents=True, exist_ok=True)

        # mkstemp hands back an open descriptor as well as the path; close it
        # so a backup run does not leak one per call.
        fd, temp_name = tempfile.mkstemp(suffix=".sql")
        os.close(fd)
        temp_sql = Path(temp_name)

        # ── Step 1: pg_dump ───────────────────────────────────────────
        self.stdout.write(f"Dumping database to {temp_sql} ...")
        try:
            env = os.environ.copy()
            env["PGPASSWORD"] = conn_parts["password"]
            subprocess.run(
                [
                    "pg_dump",
                    "-Fc",
                    "-h", conn_parts["host"],
                    "-p", conn_parts["port"],
                    "-U", conn_parts["user"],
                    "-d", conn_parts["dbname"],
                    "--no-owner",
                    "--no-acl",
                    "-f", str(temp_sql),
                ],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            temp_sql.unlink(missing_ok=True)
            raise CommandError("pg_dump not found. Install postgresql-client.")
        except subprocess.CalledProcessError as exc:
            temp_sql.unlink(missing_ok=True)
            raise CommandError(f"pg_dump failed:\n{exc.stderr}") from exc

        # ── Step 2: Compress ──────────────────────────────────────────
        self.stdout.write("Compressing dump ...")
        try:
            with open(temp_sql, "rb") as f_in:
                with gzip.open(dump_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        finally:
            temp_sql.unlink(missing_ok=True)

        file_size = dump_path.stat().st_size
        self.stdout.write(
            f"Compressed dump: {dump_path} ({self._human_size(file_size)})"
        )

        # ── Step 3: Write last_backup.txt marker ──────────────────────
        marker_path = Path(settings.BASE_DIR) / "last_backup.txt"
        marker = {
            "last_sync": datetime.now().isoformat(),
            "uploaded": False,
            # The file that was actually written — with --output this is not
            # the default timestamped name, and the dashboard widget shows it.
            "local_file": dump_path.name,
        }
        marker_path.write_text(json.dumps(marker))
        self.stdout.write(f"Backup marker written: {marker_path}")

        self.stdout.write(self.style.SUCCESS("Local backup completed successfully."))

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

    @staticmethod
    def _human_size(bytes_):
        for unit in ("B", "KB", "MB", "GB"):
            if bytes_ < 1024:
                return f"{bytes_:.1f}{unit}"
            bytes_ /= 1024
        return f"{bytes_:.1f}TB"
