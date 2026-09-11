"""
Background tasks executed via django-q2 to prevent
the HTMX checkout request from hanging on slow I/O.
"""

import logging
import os
import socket
import time

from django.conf import settings
from django.core.management import call_command

logger = logging.getLogger(__name__)

# ESC/POS: open cash drawer (Epson-compatible, pin 1)
# ESC p 0x00 0x19 0xFA
CASH_DRAWER_KICK = b'\x1B\x70\x00\x19\xFA'


def run_cloud_backup():
    """
    Wrapper around the ``cloud_backup`` management command for django-q2
    scheduling. No-ops when S3 or PostgreSQL are not configured (e.g. dev).
    """
    if not getattr(settings, "S3_BUCKET_NAME", ""):
        logger.warning("run_cloud_backup: S3_BUCKET_NAME not configured — skipping.")
        return {"status": "skipped", "reason": "S3 not configured"}
    if not os.environ.get("DATABASE_URL", "").startswith("postgres"):
        logger.warning("run_cloud_backup: DATABASE_URL is not PostgreSQL — skipping.")
        return {"status": "skipped", "reason": "not a PostgreSQL database"}
    call_command("cloud_backup")
    return {"status": "ok"}


def print_receipt(txn_id):
    """
    Build receipt lines from a Transaction, send to the thermal printer
    over TCP/IP, and optionally kick the cash drawer.

    Called asynchronously via django-q2 after every completed sale or return:
        async_task('core.tasks.print_receipt', txn.id)
    """
    from sales.models import Transaction
    from sales.receipts import build_receipt_lines

    host = getattr(settings, "PRINTER_HOST", "")
    port = getattr(settings, "PRINTER_PORT", 9100)
    kick_drawer = getattr(settings, "PRINTER_CASH_DRAWER", True)

    if not host:
        logger.info(f"print_receipt: PRINTER_HOST not configured — skipping txn #{txn_id}")
        return {"status": "skipped", "reason": "no printer host configured"}

    try:
        txn = Transaction.objects.select_related(
            'cashier', 'customer', 'session'
        ).get(id=txn_id)
    except Transaction.DoesNotExist:
        logger.error(f"print_receipt: Transaction #{txn_id} not found")
        return {"status": "error", "reason": f"Transaction #{txn_id} not found"}

    lines = build_receipt_lines(txn)
    payload = "\r\n".join(lines) + "\r\n"

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect((host, port))
            sock.sendall(payload.encode("utf-8"))
            time.sleep(0.3)
            if kick_drawer:
                sock.sendall(CASH_DRAWER_KICK)
                time.sleep(0.2)
        logger.info(f"Receipt sent to {host}:{port} for txn #{txn_id} ({len(lines)} lines)")
        return {"status": "ok", "lines": len(lines), "drawer": kick_drawer}
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        logger.error(f"Printer at {host}:{port} unreachable for txn #{txn_id}: {exc}")
        return {"status": "error", "reason": str(exc)}


def async_print_receipt(lines, printer_host=None, printer_port=None, timeout=5):
    """
    Legacy: send pre-built receipt lines to a thermal printer over TCP/IP.
    Prefer print_receipt(txn_id) for new code.
    """
    host = printer_host or getattr(settings, "PRINTER_HOST", "")
    port = printer_port or getattr(settings, "PRINTER_PORT", 9100)

    if not host:
        logger.warning("async_print_receipt: PRINTER_HOST not configured — skipping print.")
        return {"status": "skipped", "reason": "no printer host configured"}

    payload = "\r\n".join(lines) + "\r\n"

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.sendall(payload.encode("utf-8"))
            time.sleep(0.5)
        logger.info(f"Receipt sent to {host}:{port} ({len(lines)} lines)")
        return {"status": "ok", "lines": len(lines)}
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        logger.error(f"Printer at {host}:{port} unreachable: {exc}")
        return {"status": "error", "reason": str(exc)}
