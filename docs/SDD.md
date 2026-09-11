# Software Design Document (SDD)

## 1. Introduction

### 1.1 Purpose
This Software Design Document (SDD) outlines the architectural decisions, system components, and data design for the custom micro-retail Point of Sale (POS) and Inventory Management system. It serves as the technical blueprint for developers to build the system defined in the Software Requirements Specification (SRS).

### 1.2 Scope
The system is a locally hosted web application containerized via Docker. It handles real-time sales transactions, composite inventory deduction, informal credit ledgers, and background analytics. This document covers the backend framework, database architecture, deployment strategy, hardware integration, and the container registry update pipeline.

---

## 2. System Architecture

### 2.1 Architectural Overview
The software utilizes a standard **Client-Server architecture** entirely constrained within a Local Area Network (LAN) for daily operations. The server physically resides on-premises, serving a responsive web interface to client devices over the store's private Wi-Fi. 

### 2.2 Technology Stack
* **Backend Framework & ORM:** Django (Python). Django's native ORM is utilized for all database modeling, schema migrations (via `manage.py makemigrations`), session control, and transaction management.
* **Environment & Package Management:** Astral `uv`.
* **Database:** PostgreSQL. 
* **Asynchronous Task Queue:** Django-Q (using PostgreSQL as broker) or native OS cron jobs. *Celery and Redis are explicitly excluded.*
* **Frontend:** HTML5, CSS3, and a hybrid combination of **HTMX** (for data-heavy server round-trips and layout rendering) and **Alpine.js** (for reactive client-side UI states like modals and numeric keypads). The visual layer utilizes a mobile-first CSS framework (Tailwind CSS).

---

## 3. Deployment Architecture

### 3.1 Containerization Strategy
Orchestrated via **Docker Compose**. The `docker-compose.yml` will define `web` (Django) and `db` (PostgreSQL) services.
* **Critical Persistence Requirement:** The `db` service must explicitly mount a named or bind-mounted persistent local volume on the host hardware's filesystem.

### 3.2 The "WAN-Resilient" Local Host Model
* **Hosting:** Dedicated physical machine inside the retail store.
* **The CMOS Battery Prerequisite:** Physically replace the host machine's CR2032 CMOS battery before store installation.
* **Network Architecture:** Core POS logic binds to the local router and executes operations without internet access. The host's active internet connection is strictly for background updates and disaster recovery.

### 3.3 Patching, Updates & Bootstrapping
* **Registry Pipeline:** Updates executed via bash script running `docker compose pull` to fetch compiled images, followed by `docker-compose up -d`.
* **Day-1 Admin Bootstrapping:** The container must utilize an entrypoint script that checks the database for an Admin user. If none exists, it must securely consume `.env` variables to provision the primary admin account via a Django custom management command.
* **Automated Migrations:** The entrypoint script must automatically run Django native migrations (`python manage.py migrate`) on boot.

---

## 4. Data Design & Entity-Relationship Specification

### 4.1 Global Data Integrity Constraints
* **Immutability:** Strict foreign key restraints (`on_delete=models.RESTRICT`) preventing cascading deletes across all financial/ledger tables.
* **Financial Precision:** Django `DecimalField` mandated for all currency and weight values to prevent floating-point inaccuracies.
* **Atomic Transactions:** Writes affecting multiple tables must be wrapped in explicit Django database transactions using `transaction.atomic()`. To prevent race conditions, rows must be locked using `.select_for_update()`.

### 4.2 Core Database Schema Definitions (Django Models)
| Model Name | Purpose | Key Fields & Relationships |
| :--- | :--- | :--- |
| **CustomUser** | Manages system access and RBAC. | Inherits from `AbstractUser`. `role` (Admin, Manager, Cashier), `pin_code` (Hashed). |
| **Customer** | Tracks individuals for loyalty/metrics. | `first_name`, `last_name`, `loyalty_points` (DecimalField), `loyalty_enabled` (BooleanField). |
| **Product** | Stores inventory, Tingi parents, Quick Services. | `name`, `sku`, `price` (DecimalField), `stock_quantity` (DecimalField), `is_service` (BooleanField). |
| **RecipeIngredient** | Through table for Many-to-Many bundles. | `parent_product` (`ForeignKey` to Product), `child_product` (`ForeignKey` to Product), `quantity_required` (DecimalField). Explicitly configured on Product via `ManyToManyField(through='RecipeIngredient')`. |
| **Transaction** | Records macro-details of a checkout event. | `cashier` (`ForeignKey` to CustomUser), `customer` (`ForeignKey` to Customer, Nullable), `total_amount` (DecimalField), `created_at` (DateTimeField), `transaction_date` (DateTimeField), `status` (CharField/Choices: Draft, Completed, Void). |
| **TransactionLineItem** | 1st Normal Form record of exact products sold. | `transaction` (`ForeignKey` to Transaction), `product` (`ForeignKey` to Product), `quantity_sold` (DecimalField), `price_at_sale` (DecimalField). |
| **Ledger** | Immutable cashbook coupling sales/till expenses. | `transaction` (`ForeignKey` to Transaction, Nullable), `logged_by` (`ForeignKey` to CustomUser), `amount` (DecimalField), `entry_type` (CharField/Choices), `description` (TextField). |
| **CreditProfile** | Manages "Black Book" parameters per customer. | `customer` (`OneToOneField` to Customer), `current_balance` (DecimalField), `credit_limit` (DecimalField), `settlement_period_days` (IntegerField). |

### 4.3 Ledger and Transaction Coupling Logic
Every successful checkout `Transaction` must utilize a single `transaction.atomic()` block to simultaneously commit the `TransactionLineItem` records, mutate stock quantities via `F()` expressions, and write a positive entry to the `Ledger` cashbook utilizing the nullable `transaction_id` foreign key.

### 4.4 Data Seeding & Bulk Ingestion
Developers must build a custom Django management command leveraging Django ORM’s `bulk_create()` for high-performance bulk CSV parsing and ingestion of the initial 1,000+ SKUs into the `Product` and `RecipeIngredient` tables for Day-1 launch, minimizing database round-trips.
