#!/bin/sh
set -e

# ─────────────────────────────────────────────
# 13.1 — NTP Time Guardrail
# Pings a reliable IP to verify system time is
# accurate. Exits with error if grossly wrong.
# ─────────────────────────────────────────────

# Try to verify system time via HTTPS date header
# (no root privileges required for this check)
if command -v wget >/dev/null 2>&1; then
    FETCH="wget -q -O -"
elif command -v curl >/dev/null 2>&1; then
    FETCH="curl -s"
else
    FETCH=""
fi

if [ -n "$FETCH" ]; then
    # Try Google's date header as a reference
    remote_date=$(wget -q -S --max-redirect=0 --timeout=5 https://www.google.com/ 2>&1 | grep -i "^[[:space:]]*[Dd]ate:" | sed 's/.*[Dd]ate: //' 2>/dev/null) || remote_date=""

    if [ -z "$remote_date" ]; then
        remote_date=$(curl -sI --connect-timeout 5 https://www.google.com/ 2>/dev/null | grep -i "^[Dd]ate:" | sed 's/^[Dd]ate: //' 2>/dev/null) || remote_date=""
    fi

    if [ -n "$remote_date" ]; then
        remote_epoch=$(date -d "$remote_date" +%s 2>/dev/null) || remote_epoch=0
        local_epoch=$(date +%s)

        diff=$(( local_epoch > remote_epoch ? local_epoch - remote_epoch : remote_epoch - local_epoch ))

        # Allow max 24-hour drift (86400 seconds)
        if [ "$diff" -gt 86400 ]; then
            echo "ERROR: System time is off by $(echo "scale=1; $diff / 3600" | bc) hours."
            echo "       Check CMOS battery or configure NTP before booting Django."
            exit 1
        fi
        echo "NTP check passed (drift: $(echo "scale=0; $diff" | bc) sec)."
    else
        echo "NTP check skipped — could not reach reference time server."
    fi
else
    echo "NTP check skipped — neither wget nor curl available."
fi

# ─────────────────────────────────────────────
# Django: migrate, collectstatic, bootstrap
# ─────────────────────────────────────────────

python manage.py migrate --noinput

python manage.py collectstatic --noinput 2>/dev/null || true

# ─────────────────────────────────────────────
# Launch the web server
# ─────────────────────────────────────────────

exec gunicorn core.wsgi:application --bind 0.0.0.0:8000
