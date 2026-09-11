"""
13.4 — Automated Snapshot Backups
Management command that:
  1. Dumps the PostgreSQL database via pg_dump
  2. Compresses with gzip
  3. Uploads to S3-compatible storage
  4. Writes last_backup.txt marker for the dashboard widget
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

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
except ImportError:
    boto3 = None


class Command(BaseCommand):
    help = "Dump, compress, and upload PostgreSQL snapshot to S3."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-upload",
            action="store_true",
            help="Create the local dump file but skip S3 upload",
        )
        parser.add_argument(
            "--keep-local",
            action="store_true",
            help="Keep the local compressed dump file after upload",
        )

    def handle(self, *args, **options):
        no_upload = options["no_upload"]
        keep_local = options["keep_local"]

        # ── Database URL parsing ──────────────────────────────────────
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url.startswith("postgres"):
            raise CommandError(
                "cloud_backup is designed for PostgreSQL. "
                f"DATABASE_URL must be postgres:// — got: {db_url[:30]}..."
            )

        # Parse connection details from DATABASE_URL
        # Format: postgres://user:password@host:port/dbname
        conn_parts = self._parse_db_url(db_url)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dump_filename = f"eixn_pos_{timestamp}.sql.gz"
        backup_dir = Path(settings.BASE_DIR) / "backups"
        backup_dir.mkdir(exist_ok=True)
        dump_path = backup_dir / dump_filename
        temp_sql = Path(tempfile.mkstemp(suffix=".sql")[1])

        # ── Step 1: pg_dump ───────────────────────────────────────────
        self.stdout.write(f"Dumping database to {temp_sql} ...")
        try:
            env = os.environ.copy()
            env["PGPASSWORD"] = conn_parts["password"]
            subprocess.run(
                [
                    "pg_dump",
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
            raise CommandError("pg_dump not found. Install postgresql-client.")
        except subprocess.CalledProcessError as exc:
            raise CommandError(f"pg_dump failed:\n{exc.stderr}") from exc

        # ── Step 2: Compress ──────────────────────────────────────────
        self.stdout.write("Compressing dump ...")
        with open(temp_sql, "rb") as f_in:
            with gzip.open(dump_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        temp_sql.unlink()

        file_size = dump_path.stat().st_size
        self.stdout.write(f"Compressed dump: {dump_path} ({self._human_size(file_size)})")

        # ── Step 3: Upload to S3 ──────────────────────────────────────
        uploaded = False
        if no_upload:
            self.stdout.write("--no-upload: skipping S3 upload.")
        else:
            self._upload_to_s3(dump_path, dump_filename)
            uploaded = True

            if not keep_local:
                dump_path.unlink()
                self.stdout.write(f"Removed local file {dump_path}")

        # ── Step 4: Write last_backup.txt marker ──────────────────────
        # `uploaded` records whether the snapshot reached S3 so the
        # dashboard can distinguish "Synced" from "Upload pending".
        marker_path = Path(settings.BASE_DIR) / "last_backup.txt"
        marker = {
            "last_sync": datetime.now().isoformat(),
            "uploaded": uploaded,
            "local_file": dump_filename if not uploaded else None,
        }
        marker_path.write_text(json.dumps(marker))
        self.stdout.write(f"Backup marker written: {marker_path}")

        self.stdout.write(self.style.SUCCESS("Backup completed successfully."))

    def _upload_to_s3(self, local_path, object_key):
        if boto3 is None:
            raise CommandError(
                "boto3 is not installed. Run: uv add boto3"
            )

        bucket = os.environ.get("S3_BUCKET_NAME", "").strip()
        if not bucket:
            raise CommandError(
                "S3_BUCKET_NAME env var not set. Cannot upload."
            )

        endpoint_url = os.environ.get("S3_ENDPOINT_URL", None)
        region = os.environ.get("S3_REGION", "us-east-1")
        access_key = os.environ.get("S3_ACCESS_KEY_ID", None)
        secret_key = os.environ.get("S3_SECRET_ACCESS_KEY", None)

        self.stdout.write(f"Uploading to s3://{bucket}/{object_key} ...")

        try:
            kwargs = {
                "service_name": "s3",
                "region_name": region,
            }
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            if access_key and secret_key:
                kwargs["aws_access_key_id"] = access_key
                kwargs["aws_secret_access_key"] = secret_key

            client = boto3.client(**kwargs)
            client.upload_file(str(local_path), bucket, object_key)
            self.stdout.write(self.style.SUCCESS("Upload complete."))
        except NoCredentialsError as exc:
            raise CommandError("AWS credentials not found.") from exc
        except ClientError as exc:
            raise CommandError(f"S3 upload failed: {exc}") from exc

    @staticmethod
    def _parse_db_url(url):
        """
        Parse postgres://user:password@host:port/dbname into a dict.
        """
        # Remove scheme
        rest = url.split("://", 1)[1]
        userinfo, rest = rest.split("@", 1)
        user, password = userinfo.split(":", 1) if ":" in userinfo else (userinfo, "")
        host_port, dbname = rest.split("/", 1)
        if ":" in host_port:
            host, port = host_port.split(":", 1)
        else:
            host = host_port
            port = "5432"
        # Strip query params
        dbname = dbname.split("?")[0]
        return {"user": user, "password": password, "host": host, "port": port, "dbname": dbname}

    @staticmethod
    def _human_size(bytes_):
        for unit in ("B", "KB", "MB", "GB"):
            if bytes_ < 1024:
                return f"{bytes_:.1f}{unit}"
            bytes_ /= 1024
        return f"{bytes_:.1f}TB"
