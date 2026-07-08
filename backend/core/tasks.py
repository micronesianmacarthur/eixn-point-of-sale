"""
13.2 — Asynchronous Printer Handoff
Background tasks executed via django-q2 to prevent
the HTMX checkout request from hanging on slow I/O.
"""

import logging
import socket
import time

from django.conf import settings

logger = logging.getLogger(__name__)


def async_print_receipt(lines, printer_host=None, printer_port=None, timeout=5):
    """
    Send formatted receipt lines to a thermal printer over TCP/IP.

    Called asynchronously via django-q2:
        from core.tasks import async_print_receipt
        async_task('core.tasks.async_print_receipt', lines)

    Parameters
    ----------
    lines : list[str]
        Lines of text to print (they will be joined with \\r\\n).
    printer_host : str, optional
        IP or hostname of the Epson TM / Star thermal printer.
        Falls back to settings.PRINTER_HOST.
    printer_port : int, optional
        TCP port (default 9100 for Epson).
        Falls back to settings.PRINTER_PORT.
    timeout : int
        Socket timeout in seconds.
    """
    host = printer_host or getattr(settings, "PRINTER_HOST", None)
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
            time.sleep(0.5)  # allow printer buffer to flush
        logger.info(f"Receipt sent to {host}:{port} ({len(lines)} lines)")
        return {"status": "ok", "lines": len(lines)}
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        logger.error(f"Printer at {host}:{port} unreachable: {exc}")
        return {"status": "error", "reason": str(exc)}
