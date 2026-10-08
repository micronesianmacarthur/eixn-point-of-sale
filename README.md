# EIXN Point of Sale

LAN-first Point of Sale, Inventory Management, and Financial Ledger for a solo-operated micro-retailer.
Django 5 + PostgreSQL, served over the local network, with cloud backup and thermal receipt printing as
non-critical background tasks.

> This README currently covers **installation** and **business configuration** only. Development
> workflow, testing, and architecture notes will be added later.

---

## 1. Prerequisites

| Requirement | Version | Purpose |
|---|---|---|
| Python | 3.14 (`.python-version`) | Backend runtime |
| [uv](https://docs.astral.sh/uv/) | latest | Dependency / venv management |
| Docker | latest | PostgreSQL container (dev and production) |
| Docker Compose | v2 | Production stack |

Confirm the toolchain before starting:

```bash
python --version   # 3.14
uv --version
docker --version
```

---

## 2. Installation

### 2.1 Clone and install dependencies

```bash
git clone <repo-url> eixn-point-of-sale
cd eixn-point-of-sale/backend
uv sync
```

This creates `backend/.venv` from `backend/uv.lock`.

### 2.2 Create the environment file

`backend/.env` is **required** and git-ignored, so it does not exist on a fresh clone.
`core/settings.py` reads it at import time and `DATABASE_URL` has no default — without this file every
`manage.py` command (including `make build`) aborts with:

```
environs.EnvError: Environment variable "DATABASE_URL" not set
```

Create it from the template:

```bash
cd backend
cp .env.example .env
```

### 2.3 Bootstrap the database and admin user

From the repository root:

```bash
make build
```

This runs `scripts/setup-dev.sh`, which:

1. Starts a `postgres:16-alpine` container named `eixn-pos-db` on host port **5433** (deliberately offset
   from a native PostgreSQL on 5432), with database/user/password all `eixn`, and data persisted in the
   `eixn-pos-pgdata` volume.
2. Waits for PostgreSQL to accept connections.
3. Runs `manage.py migrate --noinput`.
4. Seeds the superuser **`admin` / `admin`**.

The container step is skipped if `eixn-pos-db` is already running. Re-running `make build` is safe.

<details>
<summary>Manual equivalent (if you prefer not to use <code>make</code>)</summary>

```bash
cd backend
cp .env.example .env
docker run -d --name eixn-pos-db \
  -e POSTGRES_DB=eixn_pos -e POSTGRES_USER=eixn -e POSTGRES_PASSWORD=eixn \
  -p 5433:5432 -v eixn-pos-pgdata:/var/lib/postgresql/data \
  postgres:16-alpine
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py shell -c "
from users.models import User
User.objects.get_or_create(username='admin',
    defaults={'role': User.Role.ADMIN, 'is_superuser': True, 'is_staff': True})
u = User.objects.get(username='admin'); u.set_password('admin')
u.role = User.Role.ADMIN; u.is_superuser = True; u.is_staff = True; u.save()"
```

</details>

### 2.4 Start the application

Receipt printing and cloud backup run as **background tasks** through django-q2, which requires a separate
worker process. Without it, sales still complete but **no receipt is printed**.

```bash
# Terminal 1 — HTTP server on http://localhost:8000
make dev

# Terminal 2 — background task worker
cd backend && .venv/bin/python manage.py qcluster
```

Open `http://localhost:8000/` and log in as `admin` / `admin`.

### 2.5 Stop / clean up

```bash
make stop   # stop and remove the eixn-pos-db container
make clean  # stop the container and delete __pycache__ / *.pyc
```

---

## 3. Deployment with Docker Compose

The full stack (`db`, `qcluster`, `web`) is defined in `docker-compose.yml`, built from `docker/Dockerfile`,
and publishes port `8000`.

```bash
make up      # docker compose up --build -d
make logs    # tail logs
make down    # tear down
```

The image entrypoint runs `migrate`, `collectstatic`, and the backup schedule bootstrap before starting
`gunicorn core.wsgi:application --bind 0.0.0.0:8000`. `DATABASE_URL` is injected by Compose
(`postgres://eixn:eixn@db:5432/eixn_pos`) — do **not** set it to the dev port 5433 in production.

`deploy.sh` is the registry-based rollout: `docker compose pull` → `docker compose up -d --remove-orphans`
→ `docker system prune -f` (no `--volumes`, so the `pgdata` volume is preserved).

---

## 4. Business Configuration

Configuration is split between **environment variables** (infrastructure) and **in-app settings**
(operations). Business identity is entered once through a guided setup wizard.

### 4.1 First-run setup wizard (required)

`SetupCheckMiddleware` redirects every authenticated user to **`/setup/`** until a `BusinessInfo` row
exists. This is business data, not environment configuration — there is no seed file for it.

| Field | Notes |
|---|---|
| Business name | Printed in the receipt header |
| Contact phone | Printed as `Tel <number>` in the receipt header |
| Contact email | |
| Website | |
| Logo | Optional image, max 3 MB |

Submitting the wizard lands you on the sales dashboard. Re-edit later at **`/settings/business/`**.

> In automated tests, a missing `BusinessInfo` row causes a **302** to `/setup/` rather than a 200.

### 4.2 Runtime settings — `/settings/`

Stored as key/value rows in `SystemSetting` and edited from the settings page.

| Setting | Default | Notes |
|---|---|---|
| Default markup rate | `0.15` | Applied when pricing new products |
| Default customer credit limit | — | Starting credit limit for new customers |
| Idle session timeout enabled | — | **Admins only** (Session tab) |
| Idle session timeout | 5 min (300 s) | **Admins only**; range 1–30 minutes, clamped to 60–1800 s |

Idle timeout auto-logs-out inactive users and is mirrored by a frontend watchdog in `base.html`.

### 4.3 Users, roles, and access

Authentication accepts a **password or a 4-digit PIN** (`users.backends.PinOrPasswordBackend`), so cashiers
can log in quickly on a shared terminal.

| Role | DB value | Capabilities |
|---|---|---|
| Cashier | `CASHIER` | Sell, manage own session, customers, view sales |
| Manager | `MANAGER` | Cashier + inventory CRUD, stock counts/adjustments, user management, offline recovery, settings |
| Admin | `ADMIN` | Manager + assign the Admin role, configure the Session tab |

- Default role on creation is `CASHIER`.
- `is_staff` / `is_superuser` are forced true for `ADMIN` only.
- User management lives at `/users/` and requires manager or admin; unauthorized users receive **403**.
- Only admins may create users or grant the Admin role.

### 4.4 Inventory setup

Order of operations for a new store:

1. **Vendors** — `/inventory/vendors/` (each product requires one).
2. **Categories** — `/inventory/categories/` (optional but recommended for reporting).
3. **Products** — `/inventory/products/`. Key fields:
   - `sku` (unique, optional), `name`, `vendor`, `category`
   - `cost_price`, `retail_price`, `discount_price` + `is_on_sale`
   - `stock_quantity`, `min_stock_level` (drives the low-stock report)
   - `is_service` — 100% margin service line, excluded from stock deduction
   - `is_variable_weight` — fractional quantity ("tingi") item
   - `components` — self-referential M2M for composite/recipe items

   Bulk import is available via `manage.py seed_products <csv> [--dry-run]`, and a CSV template can be
   downloaded from `/inventory/bulk-upload/template/`.

4. **Bundles** — `/inventory/bundles/`. A bundle is a named set of component products with its own
   `retail_price` (blank means price = sum of components). At checkout a bundle expands into individual
   cart lines, and stock is deducted per component inside an atomic block with row locking.

5. **Receiving** — `/inventory/receive/` to bring stock in, plus purchase orders, repackaging (`/inventory/repack/`),
   stock counts (`/inventory/count/`), and adjustments.

### 4.5 Cash sessions (open/close till)

A session must be opened before checkout is available (`require_open_session` gates the cart views).

- Open: **`/sales/sessions/create/`** — enter the starting cash float for the terminal.
- Close: **`/sales/sessions/<pk>/close/`** — a 4-step flow (count → remove variances → review → PDF) that
  produces the Z-report and session P&L. Only one session may be open at a time.

### 4.6 Customers and informal credit

`/customers/` manages customers with an informal credit ledger (payments at `/customers/<pk>/pay/`).
Credit limits are checked at checkout (`/sales/checkout/credit-check/`) against the default limit in
`/settings/` unless overridden per customer. Two reconciliation commands exist for historic balance drift:
`manage.py fix_customer_credit_balances` and `manage.py reconcile_customer_balances`.

### 4.7 Payment types

Fixed at checkout — not configurable: `CASH`, `CARD`, `ACCOUNT`, `OWNER_DRAW`.

### 4.8 Hardware and cloud configuration (environment variables)

Set in `backend/.env` for local dev, or exported in the Compose environment for production.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | insecure dev fallback | **Set a real value in production** |
| `DEBUG` | `True` | Set `False` in production |
| `ALLOWED_HOSTS` | empty | Comma-separated hostnames |
| `DATABASE_URL` | **required** | `postgres://eixn:eixn@localhost:5433/eixn_pos` locally |
| `PRINTER_HOST` | empty | Network thermal printer IP; empty disables printing |
| `PRINTER_PORT` | `9100` | Raw TCP ESC/POS port |
| `PRINTER_CASH_DRAWER` | `true` | Sends the ESC/POS drawer kick after each receipt |
| `S3_BUCKET_NAME` | empty | Enables cloud backup; empty disables it |
| `S3_ENDPOINT_URL` | empty | S3-compatible endpoint |
| `S3_REGION` | `us-east-1` | |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | empty | |

Printer and backup settings are environment-only — there is no UI for them. A backup schedule is
registered on startup by the `ensure_backup_schedule` command.

### 4.9 Fixed behaviours worth knowing

- **Time zone** is `Pacific/Pohnpei` (`TIME_ZONE`), with timezone-aware datetimes.
- **Money** is always `Decimal`, quantized to `0.01` with `ROUND_HALF_UP`. Floats are never used.
- **Tax** is not modelled — there is no tax rate on products, cart lines, or receipts.
- **Currency** is not configurable; there is no currency symbol setting.
- **Receipt layout** is hardcoded in `sales/receipts.py`: business name and phone in the header, fixed
  "THANK YOU / PLEASE KEEP THIS RECEIPT" footer.
- **Accounting** has no URL namespace; ledger and reporting surface through the sales dashboard and the
  session-close Z-report.

---

## 5. Make Targets

| Target | Purpose |
|---|---|
| `make build` | Bootstrap: start PostgreSQL, migrate, seed `admin`/`admin` |
| `make dev` | Run the Django development server |
| `make migrate` | Apply migrations |
| `make admin` | Seed or reset the `admin` user (resets password to `admin`) |
| `make shell` | Django shell |
| `make up` / `make down` / `make logs` | Docker Compose stack control |
| `make stop` | Stop and remove the dev database container |
| `make clean` | Stop container, remove caches |
| `make help` | List targets |

---

## 6. Troubleshooting

**`environs.EnvError: Environment variable "DATABASE_URL" not set`**
`backend/.env` is missing. Run `cd backend && cp .env.example .env`.

**`make build` fails connecting to PostgreSQL**
The dev container publishes **5433**, not 5432. Confirm the port in `DATABASE_URL` matches
`DB_PORT=5433` in `scripts/setup-dev.sh`, and that `eixn-pos-db` is running (`docker ps`).

**Sales complete but no receipt prints**
No django-q2 worker is running. Start `cd backend && .venv/bin/python manage.py qcluster` in a second
terminal. Also check `PRINTER_HOST` is set — an empty value disables printing. Printer failures are
logged and swallowed, so a sale is never blocked by a printer error.

**Authenticated requests redirect to `/setup/`**
`BusinessInfo` has no row yet — `SetupCheckMiddleware` redirects to the setup wizard. Complete it, or
create the row programmatically in tests.

**403 instead of a redirect**
Manager/admin-only views use `UserPassesTestMixin`, which returns **403** rather than 302. The account
lacks the required role.

**Backup never runs**
`S3_BUCKET_NAME` is unset (backup skipped) or `DATABASE_URL` is not PostgreSQL. `core.tasks.run_cloud_backup`
requires both.