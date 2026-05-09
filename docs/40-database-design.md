# Database Design — `bitcheck`

> **Status:** Draft v0.2 — handoff to backend team
> **Parent:** [`00-platform-plan.md`](./00-platform-plan.md)
> **Audience:** Django backend team. This is the schema we want them to implement.
> **Stack assumed:** PostgreSQL 15+, Django 5, DRF, Celery + Redis. Object storage S3-compatible.
>
> **Changes from v0.1:**
> - Internal currency is now **bit tokens** (`_bits` suffix), not kobo. Naira appears only at the Squad boundary.
> - **Single wallet system** for both B2C and B2B. `token_wallets` belongs to either a `User` (B2C) or an `Organization` (B2B), enforced by XOR check.
> - **Subscriptions schedule monthly bit grants** to user wallets. Top-ups credit org wallets. Verifications debit either. One ledger, one debit path.
> - Rate locked at **₦100 = 1 bit token** (₦1000 = 10 bits) for the hackathon. Lives in settings, not the DB.

---

## 0. TL;DR

This doc defines every table the backend needs for the hackathon MVP, grouped by domain:

1. **Identity & access** — users, organizations, memberships
2. **Plans & subscriptions** (B2C) — plans, subscriptions
3. **Tokens & top-ups** (B2B) — virtual accounts, token wallets, ledger, top-ups
4. **API keys** (B2B)
5. **Verifications** (core domain) — uploaded files, verifications, jobs
6. **Usage logs** (B2B) — api_calls
7. **Webhooks** — webhook_events
8. **Audit** — audit_logs (stretch)

Every table is documented with fields, constraints, indexes, and notes on *why* the shape is what it is.

---

## 1. Universal conventions

These apply to every table unless explicitly overridden.

| Concern | Rule |
|---|---|
| **Primary key** | UUID v4 for any entity that may appear in URLs, API responses, or cross-system references (users, orgs, verifications, api keys, top-ups, webhook events). Big-int auto-increment is fine for purely-internal tables (ledger entries, api_calls, sessions). |
| **Naming** | `snake_case`. Singular column names, plural table names (`users`, not `user`). |
| **Timestamps** | Every table has `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`. Most have `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` driven by a Django `auto_now` field. |
| **Soft delete** | We **don't** soft-delete by default. Add `deleted_at TIMESTAMPTZ NULL` only on tables explicitly marked as soft-delete (verifications, api_keys). |
| **Foreign keys** | Suffix `_id`. Use `ON DELETE` rule explicitly per FK (cascade vs set-null vs restrict). Default in this doc: `ON DELETE RESTRICT` unless noted. |
| **Internal currency** | **Bit tokens** (`_bits` suffix). All balances, debits, plan grants, and usage costs are stored as `BIGINT` bit tokens. **Never store kobo, decimals, or floats internally.** |
| **External currency** | **Whole naira** (`_naira` suffix), `BIGINT`. Used **only** on rows that mirror a Squad transaction (`top_ups.amount_naira`, `plans.recurring_charge_naira`). Convert kobo↔naira at the Squad API boundary (×100 / ÷100). |
| **Conversion rate** | `BITCHECK_NAIRA_PER_BIT` lives in Django settings/env (hackathon value: `100`). Rate snapshot is captured per `top_up` so historical rows stay correct if the rate changes. |
| **Booleans** | Prefixed `is_` or `has_` (`is_active`, `has_completed_kyc`). |
| **Enums** | Use Postgres native `CHECK` constraints over text columns rather than PG ENUM types (easier to extend without migrations). Django side: `TextChoices`. |
| **Indexes** | Every FK gets an index. Every column used in a `WHERE` of a hot query gets an index. Composite indexes are spelled out per table. |
| **JSONB** | Use for ML responses, raw webhook payloads, and structured "result summaries" we don't want to normalize. Always nullable, default `'{}'::jsonb`. |
| **Postgres extensions** | `pgcrypto` (for `gen_random_uuid()`) and `citext` (for case-insensitive emails). Enable in initial migration. |
| **Time zones** | Always TIMESTAMPTZ. Server runs UTC. Display tz handled in frontend. |

---

## 2. Suggested Django app layout

One Django app per domain group. Keeps migrations contained and lets teams own areas:

```
apps/
  accounts/        # User, Organization, Membership
  billing/         # Plan, Subscription (drives B2C bit grants)
  bits/            # TokenWallet, TokenLedgerEntry, VirtualAccount, TopUp
                   #   The unified bit-token accounting layer for B2C + B2B.
  api_keys/        # ApiKey
  verifications/   # UploadedFile, Verification, VerificationJob
  usage/           # ApiCall
  webhooks/        # WebhookEvent
  audit/           # AuditLog (optional, stretch)
```

`accounts.User` is the **`AUTH_USER_MODEL`** from the very first migration. Setting this later requires a painful reset.

---

## 3. ER overview

High-level, grouped by domain. FK arrows point from the child to the parent.

```
                       ┌─────────────┐
                       │    User     │ ◄─── auth, identity
                       └──────┬──────┘
              ┌───────────────┼──────────────┬──────────────┐
              ▼               ▼              ▼              ▼
       ┌──────────┐   ┌─────────────┐  ┌──────────┐  ┌────────────┐
       │Membership│──►│Organization │  │TokenWallet│  │Subscription│
       └──────────┘   └──────┬──────┘  │ (B2C 1:1) │  │  (B2C)     │
                             │         └─────┬─────┘  └─────┬──────┘
       ┌─────────────────────┼──────────┐    │              │
       ▼                     ▼          ▼    │              ▼
  ┌─────────┐         ┌────────────┐  ┌──┴───┴─┐    ┌──────────┐
  │ ApiKey  │         │TokenWallet │  │ same   │    │   Plan   │
  └────┬────┘         │ (B2B 1:1)  │  │ table  │    └──────────┘
       │              └─────┬──────┘  │ (XOR)  │
       │                    │         └────┬───┘
       │                    └──────┬───────┘
       │                           ▼
       │                  ┌─────────────────┐
       │                  │ TokenLedgerEntry│ ◄── append-only credits/debits
       │                  └────────┬────────┘
       │                           ▲
       │                           │ credit
       │                  ┌────────┴────────┐
       │                  │     TopUp       │ ◄── B2B Squad webhook
       │                  └────────┬────────┘
       │                           │
       │                  ┌────────┴────────┐
       │                  │ VirtualAccount  │ ◄── 1:1 with Organization
       │                  └─────────────────┘
       │
       └────────────────┐
                        ▼
                 ┌─────────────┐         debit
                 │  ApiCall    │ ─────────────────► TokenLedgerEntry
                 └──────┬──────┘
                        │
            ┌───────────┴────────────┐
            ▼                        ▼
     ┌──────────────┐         ┌──────────────┐
     │ Verification │────────►│ UploadedFile │
     └──────┬───────┘         └──────────────┘
            │
            ▼
     ┌──────────────────┐
     │ VerificationJob  │  (1:1 with Verification)
     └──────────────────┘

         (separately)
                    ┌────────────────┐
                    │ WebhookEvent   │ ◄── all incoming Squad events
                    └────────────────┘
                    ┌────────────────┐
                    │  AuditLog      │ ◄── stretch
                    └────────────────┘

  Note: TokenWallet is ONE table with XOR ownership (user XOR organization).
        Drawn split here for clarity.
```

---

## 4. Schema

---

### 4.1 Identity & access

#### `users`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, default `gen_random_uuid()` | |
| `email` | citext | NOT NULL, UNIQUE | Case-insensitive |
| `password_hash` | text | NOT NULL | Django manages |
| `full_name` | text | NULL | Optional at signup |
| `account_type` | text | NOT NULL, CHECK in (`'individual'`, `'business'`) | Drives default landing surface (`/app` vs `/business`) |
| `is_active` | boolean | NOT NULL, DEFAULT true | Standard Django |
| `is_staff` | boolean | NOT NULL, DEFAULT false | Standard Django |
| `email_verified_at` | TIMESTAMPTZ | NULL | Stub for now; we trust the email at signup in MVP |
| `last_login_at` | TIMESTAMPTZ | NULL | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Indexes:** `UNIQUE (email)`.

**Notes:**
- This is `AUTH_USER_MODEL`. Extend `AbstractBaseUser` + `PermissionsMixin`, not `AbstractUser` (we don't want the `username` field).
- `account_type` is a UX hint, not a security boundary. A user marked `individual` can still join an org via membership. Authorization checks must use memberships, not this field.

---

#### `organizations`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `name` | text | NOT NULL | Business name shown in UI + on virtual account |
| `slug` | citext | NOT NULL, UNIQUE | URL-safe; auto-generated from `name` on create |
| `created_by_id` | UUID | NOT NULL, FK → `users.id`, ON DELETE RESTRICT | Founder; doesn't change ownership semantics — that's `memberships.role` |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Indexes:** `UNIQUE (slug)`, `INDEX (created_by_id)`.

---

#### `memberships`

Links users to orgs with a role. We use this even for the 1:1 hackathon case so growth is free.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `user_id` | UUID | NOT NULL, FK → `users.id`, ON DELETE CASCADE | |
| `organization_id` | UUID | NOT NULL, FK → `organizations.id`, ON DELETE CASCADE | |
| `role` | text | NOT NULL, CHECK in (`'owner'`, `'admin'`, `'member'`) | Hackathon: every membership = `'owner'`. |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Indexes:** `UNIQUE (user_id, organization_id)`, `INDEX (organization_id)`.

---

### 4.2 Authentication

For the hackathon, **lean on Django's built-in session framework** (`django.contrib.sessions`) backed by Redis or the DB. No custom session table needed.

If a JWT pattern is preferred for the SPA, use **`djangorestframework-simplejwt`** with httpOnly refresh cookie — no schema additions; the library manages everything.

**Decision needed:** session vs JWT. Default recommendation for hackathon = **Django sessions in DB**, simplest end-to-end.

---

### 4.3 Plans & subscriptions (B2C)

#### `plans`

Static catalog. Seeded, not user-created. A plan's job is to define **how many bit tokens are granted to the user's wallet on each billing period.**

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `code` | text | NOT NULL, UNIQUE, CHECK in (`'free'`, `'pro'`) | Stable identifier used in code |
| `name` | text | NOT NULL | Display name |
| `recurring_charge_naira` | bigint | NOT NULL, DEFAULT 0 | Whole-naira amount Squad debits per period. `0` for free. Multiplied by 100 at the Squad API boundary. |
| `monthly_grant_bits` | bigint | NOT NULL, CHECK (`monthly_grant_bits >= 0`) | Bit tokens credited to the user's wallet at the start of each period. |
| `billing_interval` | text | NOT NULL, CHECK in (`'none'`, `'monthly'`) | `none` for free |
| `is_active` | boolean | NOT NULL, DEFAULT true | Allows retiring plans without deletion |
| `created_at` / `updated_at` | TIMESTAMPTZ | | |

**Indexes:** `UNIQUE (code)`.

**Seed:**
```
('free', 'Free',     0,    3,    'none')      ← TBD numbers
('pro',  'Pro',   5000,   50,    'monthly')   ← TBD numbers
```

> **Display reminder:** `recurring_charge_naira` is naira (e.g. `5000`), not kobo. The frontend formats this as `₦5,000`. Squad gets `recurring_charge_naira × 100` kobo when initialising the mandate.

---

#### `subscriptions`

One row per (user, plan) lifecycle. The `current` subscription for a user is the row with `status` in (`'active'`, `'past_due'`, `'paused'`).

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `user_id` | UUID | NOT NULL, FK → `users.id`, ON DELETE CASCADE | Subscriptions are personal, not org-level |
| `plan_id` | UUID | NOT NULL, FK → `plans.id`, ON DELETE RESTRICT | |
| `status` | text | NOT NULL, CHECK in (`'incomplete'`, `'active'`, `'past_due'`, `'canceled'`, `'paused'`) | See § 5 for state machine |
| `current_period_start` | TIMESTAMPTZ | NOT NULL | |
| `current_period_end` | TIMESTAMPTZ | NOT NULL | |
| `cancel_at_period_end` | boolean | NOT NULL, DEFAULT false | "Don't renew" flag |
| `canceled_at` | TIMESTAMPTZ | NULL | When the user clicked cancel |
| `squad_subscription_id` | text | NULL, UNIQUE | Mandate id from Squad for recurring debit |
| `squad_customer_id` | text | NULL | |
| `created_at` / `updated_at` | TIMESTAMPTZ | | |

**Indexes:** `UNIQUE (squad_subscription_id) WHERE squad_subscription_id IS NOT NULL`, `INDEX (user_id, status)`.

**Constraint:** at most one row per user where `status IN ('active', 'past_due', 'paused')`.
```sql
CREATE UNIQUE INDEX one_active_sub_per_user
  ON subscriptions(user_id)
  WHERE status IN ('active', 'past_due', 'paused');
```

**Notes:**
- Every user has an `active` subscription. Free users have a row pointing to the free plan, no Squad mandate. Pro users have a row with `squad_subscription_id` set.
- **Period rollover** (Celery beat task, runs hourly, picks rows where `current_period_end <= now()` and `status = 'active'`):
  1. Reset the user's `token_wallet` balance (write a ledger entry of `-current_balance`, type `'period_reset'`).
  2. Credit the wallet with `plan.monthly_grant_bits` (entry type `'subscription_grant'`).
  3. Advance `current_period_start` and `current_period_end` by one month.
- **Use-it-or-lose-it** for B2C subscriptions. Unused bits don't roll over. (B2B top-ups DO accrue — they're separate entries with no reset step.)
- **Upgrade flow** (Free → Pro mid-period): on Squad mandate confirmation, cancel the free subscription, create a Pro subscription with `current_period_start = now()`, immediately credit the Pro grant. No proration.

---

### 4.4 Bit token wallets, ledger & top-ups

The unified accounting layer. Every account (B2C user or B2B org) has exactly one wallet. Every credit and debit is recorded in the ledger. There is no parallel quota system.

#### `virtual_accounts`

1:1 with organizations. Created at org-signup time via Squad API. **B2B only** — B2C users top up by upgrading to Pro, not by bank transfer.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `organization_id` | UUID | NOT NULL, UNIQUE, FK → `organizations.id`, ON DELETE CASCADE | |
| `bank_name` | text | NOT NULL | e.g. "GTBank" |
| `account_number` | text | NOT NULL, UNIQUE | NUBAN |
| `account_name` | text | NOT NULL | e.g. "ACME CORP / BITCHECK" |
| `squad_account_reference` | text | NOT NULL, UNIQUE | Squad's internal id |
| `created_at` / `updated_at` | TIMESTAMPTZ | | |

**Indexes:** `UNIQUE (organization_id)`, `UNIQUE (account_number)`.

---

#### `token_wallets`

1:1 with **either** a user (B2C) **or** an organization (B2B). Same table, XOR ownership.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `owner_user_id` | UUID | NULL, UNIQUE, FK → `users.id`, ON DELETE CASCADE | Set for B2C wallets |
| `owner_organization_id` | UUID | NULL, UNIQUE, FK → `organizations.id`, ON DELETE CASCADE | Set for B2B wallets |
| `balance_bits` | bigint | NOT NULL, DEFAULT 0, CHECK (`balance_bits >= 0`) | Materialized; updated transactionally with ledger writes |
| `created_at` / `updated_at` | TIMESTAMPTZ | | |

**Indexes:** `UNIQUE (owner_user_id)`, `UNIQUE (owner_organization_id)`.

**Constraint:**
```sql
CHECK ( (owner_user_id IS NOT NULL)::int + (owner_organization_id IS NOT NULL)::int = 1 )
```

**Lifecycle:**
- Create a wallet immediately on user signup AND on org creation (in the same transaction as the user/org row, ideally).
- Initial balance = 0. The first credit comes from the free-plan grant (B2C) or the first top-up (B2B).

**Consistency rule:** every write to `balance_bits` happens in the same DB transaction as the matching `token_ledger_entries` insert. Never update one without the other. Use `SELECT … FOR UPDATE` on the wallet row inside the transaction to prevent races.

---

#### `token_ledger_entries`

Append-only audit trail. Every change to any wallet, by anything (subscription grant, top-up, verification debit, manual adjustment), is one row here. Never deleted, never updated.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | bigserial | PK | |
| `wallet_id` | UUID | NOT NULL, FK → `token_wallets.id`, ON DELETE RESTRICT | |
| `delta_bits` | bigint | NOT NULL, CHECK (`delta_bits <> 0`) | Positive = credit, negative = debit |
| `balance_after_bits` | bigint | NOT NULL, CHECK (`balance_after_bits >= 0`) | Snapshot for audit |
| `entry_type` | text | NOT NULL, CHECK in (`'subscription_grant'`, `'period_reset'`, `'topup'`, `'usage'`, `'adjustment'`, `'refund'`) | See entry-type rules below |
| `reference_type` | text | NULL | e.g. `'subscription'`, `'top_up'`, `'verification'`, `'adjustment'` |
| `reference_id` | UUID or text | NULL | FK to source row — kept loose to avoid cross-table FK soup |
| `note` | text | NULL | Human-readable context for adjustments |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `created_by_id` | UUID | NULL, FK → `users.id` | Set for manual adjustments |

**Indexes:** `INDEX (wallet_id, created_at DESC)`, `INDEX (reference_type, reference_id)`.

**Entry-type rules (who writes what, when):**
| Type | Sign | Source | When |
|---|---|---|---|
| `subscription_grant` | + | Subscription rollover (or upgrade) | Beginning of each period for B2C |
| `period_reset` | – | Subscription rollover | Same transaction as `subscription_grant`, zeroes out unused B2C bits |
| `topup` | + | Squad webhook (B2B virtual account credited) | When `top_ups.status` flips to `credited` |
| `usage` | – | `verifications` completion | When a verification completes successfully |
| `adjustment` | ± | Admin action | Manual; `created_by_id` and `note` required |
| `refund` | + | Reverses a `usage` entry | When ML fails after debit, or admin refund |

---

#### `top_ups`

One row per credited bank transfer to a B2B virtual account.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `organization_id` | UUID | NOT NULL, FK → `organizations.id`, ON DELETE CASCADE | |
| `virtual_account_id` | UUID | NOT NULL, FK → `virtual_accounts.id`, ON DELETE RESTRICT | |
| `amount_naira` | bigint | NOT NULL, CHECK (`amount_naira > 0`) | Whole naira that hit the account (Squad sent kobo; we ÷100 at boundary) |
| `bits_credited` | bigint | NOT NULL, CHECK (`bits_credited > 0`) | `amount_naira / rate_naira_per_bit` |
| `rate_naira_per_bit` | integer | NOT NULL, CHECK (`rate_naira_per_bit > 0`) | Snapshot of rate at the time, so historical rows aren't lying |
| `status` | text | NOT NULL, CHECK in (`'pending'`, `'credited'`, `'failed'`) | See § 5 |
| `squad_transaction_reference` | text | NOT NULL, UNIQUE | From webhook payload |
| `webhook_event_id` | UUID | NOT NULL, FK → `webhook_events.id`, ON DELETE RESTRICT | The event that created this row |
| `credited_at` | TIMESTAMPTZ | NULL | Set when status = `'credited'` |
| `created_at` / `updated_at` | TIMESTAMPTZ | | |

**Indexes:** `INDEX (organization_id, created_at DESC)`, `UNIQUE (squad_transaction_reference)`.

**Idempotency:** `squad_transaction_reference` is unique, so re-processing the same webhook is a no-op.

**Edge case — sub-rate transfers:** if `amount_naira < rate_naira_per_bit` (e.g. someone transfers ₦50 when the rate is ₦100/bit), the record is still inserted with `status = 'failed'`, no wallet credit, and a customer-visible note explaining the minimum. Decide policy with product before launch.

---

### 4.5 API keys (B2B)

#### `api_keys`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `organization_id` | UUID | NOT NULL, FK → `organizations.id`, ON DELETE CASCADE | |
| `name` | text | NOT NULL | "production", "ci", whatever the user typed |
| `environment` | text | NOT NULL, CHECK in (`'test'`, `'live'`) | |
| `prefix` | text | NOT NULL | First 12 chars, e.g. `bk_live_a8f3` — safe to display |
| `hashed_secret` | text | NOT NULL | SHA-256 (hex) of the full secret + a server-side pepper |
| `last_used_at` | TIMESTAMPTZ | NULL | Updated on each successful auth |
| `revoked_at` | TIMESTAMPTZ | NULL | Soft-delete; revoked keys remain for audit |
| `created_by_id` | UUID | NULL, FK → `users.id`, ON DELETE SET NULL | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Indexes:** `INDEX (organization_id, revoked_at)`, `UNIQUE (prefix)` (collision handling: regenerate on insert).

**Auth flow:** request comes in with `Authorization: Bearer bk_live_a8f3…full…secret`.
1. Strip prefix, look up key by `prefix`.
2. Hash the full string with the same algo + pepper.
3. Constant-time compare against `hashed_secret`.
4. Reject if `revoked_at IS NOT NULL`.
5. Update `last_used_at` async.

**Never store the raw secret.** Reveal-once UI on the frontend means we generate, return once, and forget.

---

### 4.6 Verifications (core)

#### `uploaded_files`

Storage references. Files live in S3-compatible object storage; we keep the key.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `owner_user_id` | UUID | NULL, FK → `users.id`, ON DELETE CASCADE | One of these two is set |
| `owner_organization_id` | UUID | NULL, FK → `organizations.id`, ON DELETE CASCADE | One of these two is set |
| `bucket` | text | NOT NULL | Storage bucket name |
| `storage_key` | text | NOT NULL | Object key |
| `mime_type` | text | NOT NULL | |
| `size_bytes` | bigint | NOT NULL, CHECK (`size_bytes > 0`) | |
| `sha256` | text | NOT NULL | For dedup + integrity |
| `original_filename` | text | NULL | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `deleted_at` | TIMESTAMPTZ | NULL | Soft-delete for retention policy |

**Indexes:** `INDEX (owner_user_id)`, `INDEX (owner_organization_id)`, `INDEX (sha256)`.

**Constraint:**
```sql
CHECK ( (owner_user_id IS NOT NULL)::int + (owner_organization_id IS NOT NULL)::int = 1 )
```

**Upload flow:** frontend asks Django for a presigned PUT URL (Django creates the row in `uploaded_files` with bucket + key, no file yet). Frontend uploads directly to storage. Frontend then POSTs to `/v1/verifications` with the `uploaded_file_id`.

**Retention:** policy TBD. Probably "delete file blob after N days, keep row for audit." Open question.

---

#### `verifications`

The core domain entity. One row per verification job, regardless of B2C or B2B origin.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `user_id` | UUID | NULL, FK → `users.id`, ON DELETE CASCADE | Set for B2C |
| `organization_id` | UUID | NULL, FK → `organizations.id`, ON DELETE CASCADE | Set for B2B |
| `api_key_id` | UUID | NULL, FK → `api_keys.id`, ON DELETE SET NULL | Set for B2B (which key triggered) |
| `api_call_id` | UUID | NULL, FK → `api_calls.id`, ON DELETE SET NULL | Set for B2B (which request) |
| `uploaded_file_id` | UUID | NULL, FK → `uploaded_files.id`, ON DELETE SET NULL | Null for text modality |
| `text_input` | text | NULL | Set for text modality |
| `modality` | text | NOT NULL, CHECK in (`'image'`, `'video'`, `'audio'`, `'document'`, `'text'`) | |
| `bits_charged` | integer | NOT NULL, DEFAULT 0 | Bit tokens debited from the owner's wallet on completion. Same field for B2C and B2B. |
| `status` | text | NOT NULL, CHECK in (`'queued'`, `'analyzing'`, `'completed'`, `'failed'`, `'canceled'`) | See § 5 |
| `trust_score` | integer | NULL, CHECK (`trust_score BETWEEN 0 AND 100`) | Set when status = `'completed'` |
| `verdict` | text | NULL, CHECK in (`'authentic'`, `'suspicious'`, `'manipulated'`, `'inconclusive'`) | Derived from `trust_score` + signals |
| `result_summary` | jsonb | NOT NULL, DEFAULT `'{}'` | Frontend-renderable: signals list, regions, metadata |
| `error_message` | text | NULL | Set when status = `'failed'` |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `started_at` | TIMESTAMPTZ | NULL | When ML picked it up |
| `completed_at` | TIMESTAMPTZ | NULL | |
| `deleted_at` | TIMESTAMPTZ | NULL | Soft-delete |

**Indexes:**
- `INDEX (user_id, created_at DESC) WHERE deleted_at IS NULL`
- `INDEX (organization_id, created_at DESC) WHERE deleted_at IS NULL`
- `INDEX (api_key_id, created_at DESC)`
- `INDEX (status) WHERE status IN ('queued', 'analyzing')` — for queue dashboards

**Constraints:**
```sql
-- Exactly one owner
CHECK ( (user_id IS NOT NULL)::int + (organization_id IS NOT NULL)::int = 1 )

-- Exactly one input source
CHECK ( (uploaded_file_id IS NOT NULL)::int + (text_input IS NOT NULL)::int = 1 )

-- B2B-only fields require organization_id
CHECK ( api_key_id IS NULL OR organization_id IS NOT NULL )
CHECK ( api_call_id IS NULL OR organization_id IS NOT NULL )
```

**`result_summary` shape (informal — frontend contract):**
```json
{
  "signals": [
    {"key": "exif_intact",      "ok": true,  "label": "EXIF metadata intact"},
    {"key": "gan_artifacts",    "ok": true,  "label": "No GAN artifacts detected"},
    {"key": "compression",      "ok": false, "label": "Mild recompression detected", "weight": 5}
  ],
  "regions": [               // image only — heatmap polygons
    {"x": 0.12, "y": 0.34, "w": 0.20, "h": 0.15, "score": 0.73}
  ],
  "metadata": {
    "camera": "iPhone 14 Pro",
    "captured_at": "2026-05-08T10:22:11Z"
  }
}
```

The full ML response (raw) lives in `verification_jobs.ml_response` for debugging — not in this table.

---

#### `verification_jobs`

1:1 with `verifications`. Tracks queue state and stores the raw ML response separately so the user-facing `verifications` table stays clean. **Optional for hackathon** — you can fold these fields into `verifications` if you want fewer joins.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `verification_id` | UUID | NOT NULL, UNIQUE, FK → `verifications.id`, ON DELETE CASCADE | |
| `celery_task_id` | text | NULL | Cross-ref into Celery |
| `attempts` | integer | NOT NULL, DEFAULT 0 | |
| `last_error` | text | NULL | |
| `ml_endpoint` | text | NULL | Which ML service we hit |
| `ml_response_raw` | jsonb | NOT NULL, DEFAULT `'{}'` | Full response from the ML team |
| `enqueued_at` | TIMESTAMPTZ | NULL | |
| `started_at` | TIMESTAMPTZ | NULL | |
| `completed_at` | TIMESTAMPTZ | NULL | |
| `created_at` / `updated_at` | TIMESTAMPTZ | | |

**Indexes:** `UNIQUE (verification_id)`, `INDEX (celery_task_id)`.

---

### 4.7 Usage logs (B2B)

#### `api_calls`

One row per API request. This table will grow fast — design for write-heavy + range scans.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `organization_id` | UUID | NOT NULL, FK → `organizations.id`, ON DELETE CASCADE | |
| `api_key_id` | UUID | NULL, FK → `api_keys.id`, ON DELETE SET NULL | Null only if request failed before auth |
| `endpoint` | text | NOT NULL | e.g. `POST /v1/verifications` |
| `modality` | text | NULL, CHECK in (`'image'`, `'video'`, `'audio'`, `'document'`, `'text'`) | Null for non-verification endpoints |
| `http_status` | integer | NOT NULL | 200, 401, 429, 500 |
| `bits_charged` | integer | NOT NULL, DEFAULT 0 | Bit tokens deducted; mirrors `verifications.bits_charged` for the matching row |
| `latency_ms` | integer | NOT NULL | |
| `request_id` | text | NOT NULL, UNIQUE | We expose this to customers in response headers |
| `idempotency_key` | text | NULL | If client sent `Idempotency-Key` header |
| `client_ip` | inet | NULL | |
| `user_agent` | text | NULL | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Indexes:**
- `UNIQUE (request_id)`
- `INDEX (organization_id, created_at DESC)` — drives the usage page
- `INDEX (api_key_id, created_at DESC)`
- `UNIQUE (api_key_id, idempotency_key) WHERE idempotency_key IS NOT NULL` — enforces idempotency per key

**Scaling note (post-hackathon):** when this table crosses ~10M rows, partition by month (`PARTITION BY RANGE (created_at)`). Not needed for the demo.

---

### 4.8 Webhooks

#### `webhook_events`

Every incoming event from external systems (Squad first; future: ML callbacks). The append-only inbox.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `source` | text | NOT NULL, CHECK in (`'squad'`) | Easy to extend |
| `event_type` | text | NOT NULL | e.g. `'charge.successful'`, `'transfer.successful'` |
| `external_id` | text | NULL | Provider's own event id, if available |
| `signature` | text | NULL | The HMAC header we received |
| `payload` | jsonb | NOT NULL | Raw body |
| `headers` | jsonb | NOT NULL, DEFAULT `'{}'` | All headers, for replay |
| `status` | text | NOT NULL, CHECK in (`'received'`, `'processed'`, `'failed'`, `'ignored'`), DEFAULT `'received'` | |
| `processing_error` | text | NULL | |
| `received_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `processed_at` | TIMESTAMPTZ | NULL | |

**Indexes:**
- `UNIQUE (source, external_id) WHERE external_id IS NOT NULL` — idempotency for providers that send IDs
- `INDEX (status, received_at)` — for retry workers

**Processing rule:** the HTTP handler does ONLY two things — verify signature, insert row. Actual processing happens in a Celery worker that picks up `status = 'received'` rows. This decouples response time from business logic and makes retries trivial.

---

### 4.9 Audit (stretch)

#### `audit_logs`

Optional for hackathon. Useful for B2B trust signals later ("show me everything that happened on my account").

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | bigserial | PK | |
| `actor_user_id` | UUID | NULL, FK → `users.id`, ON DELETE SET NULL | |
| `organization_id` | UUID | NULL, FK → `organizations.id`, ON DELETE SET NULL | |
| `action` | text | NOT NULL | e.g. `'api_key.created'`, `'subscription.canceled'` |
| `target_type` | text | NULL | |
| `target_id` | text | NULL | |
| `metadata` | jsonb | NOT NULL, DEFAULT `'{}'` | |
| `ip` | inet | NULL | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Indexes:** `INDEX (organization_id, created_at DESC)`, `INDEX (actor_user_id, created_at DESC)`.

---

## 5. State machines

### 5.1 `subscriptions.status`

```
            (signup, free)
                  │
                  ▼
              ┌────────┐
              │ active │ ◄──────────────┐
              └───┬────┘                │
       (upgrade) │                      │ (Squad webhook: charge succeeds)
                  ▼                      │
            ┌────────────┐              │
            │incomplete  │ ─────────────┘
            └─────┬──────┘  (init Squad mandate)
                  │
                  │ (charge fails)
                  ▼
            ┌──────────┐
            │ past_due │ ── (3 retries) ──┐
            └────┬─────┘                  │
                 │ (recovers)             ▼
                 └──► active        ┌──────────┐
                                    │ canceled │
                 (user cancels) ───►│          │
                                    └──────────┘
```

### 5.2 `verifications.status`

```
queued ──► analyzing ──► completed
   │            │
   │            └──► failed
   │
   └──► canceled  (user cancels while queued)
```

### 5.3 `top_ups.status`

```
pending ──► credited       (webhook processed, ledger entry written)
   │
   └──► failed             (webhook said failed, OR processing exception)
```

`pending` is essentially a transient state for the duration of one DB transaction. If you only ever insert as `credited`, that's also fine for the hackathon — the column exists for future "delayed credit" cases (e.g. AML review).

---

## 6. Money & token handling rules

The rules a bug here would burn the company. Worth reading once and tattooing.

1. **Bit tokens are the only internal currency.** All wallet balances, ledger deltas, verification costs, and plan grants are stored as `BIGINT` bit tokens. Never store kobo, decimals, or floats internally.

2. **Naira is a boundary unit.** It appears on exactly two columns: `top_ups.amount_naira` (what hit the bank account) and `plans.recurring_charge_naira` (what we tell Squad to debit). Both are whole-naira `BIGINT`s.

3. **Squad is kobo-native; we are not.** Convert at the edge: `kobo_for_squad = naira × 100`, `naira_from_squad_webhook = kobo_in_payload // 100`. Never persist kobo in our DB (the raw kobo in `webhook_events.payload` doesn't count — that's an opaque audit blob).

4. **Conversion rate** lives in `BITCHECK_NAIRA_PER_BIT` (settings/env). Hackathon: `100`. Snapshot per top-up via `top_ups.rate_naira_per_bit` so historical rows stay correct if we change the rate later.

5. **Wallet writes are transactional with ledger writes.** Every change to `token_wallets.balance_bits` MUST be in the same DB transaction as the matching `token_ledger_entries` insert. Pattern:
   ```python
   with transaction.atomic():
       wallet = TokenWallet.objects.select_for_update().get(pk=wallet_id)
       new_balance = wallet.balance_bits + delta
       if new_balance < 0:
           raise InsufficientBits
       wallet.balance_bits = new_balance
       wallet.save(update_fields=['balance_bits', 'updated_at'])
       TokenLedgerEntry.objects.create(
           wallet=wallet,
           delta_bits=delta,
           balance_after_bits=new_balance,
           entry_type=entry_type,
           reference_type=reference_type,
           reference_id=reference_id,
       )
   ```

6. **Subscription rollover writes two ledger entries** in one transaction: a `period_reset` (negative, zeroes out the wallet) and a `subscription_grant` (positive, adds the plan grant). This keeps "use-it-or-lose-it" verifiable from the ledger alone.

7. **Verification charging is idempotent.** Use the `request_id` (or client `Idempotency-Key`) as the natural key for "did we already charge for this?" Look up in `api_calls` before debiting.

8. **Bits debited only on successful verification.** The wallet check happens at request time (we reject if `balance_bits < cost`), but the actual debit ledger entry is written only when `verifications.status` flips to `'completed'`. If ML fails, no debit. This means the API response should clearly say "0 bits charged" on failure so customers trust it.

9. **One wallet per owner, enforced at the DB level.** Both `UNIQUE (owner_user_id)` and `UNIQUE (owner_organization_id)` are enforced. Application code should never have to deduplicate.

---

## 7. Indexes — at-a-glance

Anything not covered above:

```sql
-- Hot paths
CREATE INDEX users_email_lower             ON users (lower(email));   -- if not citext
CREATE INDEX verifications_user_recent     ON verifications (user_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX verifications_org_recent      ON verifications (organization_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX api_calls_org_recent          ON api_calls (organization_id, created_at DESC);
CREATE INDEX token_ledger_wallet_recent    ON token_ledger_entries (wallet_id, created_at DESC);
CREATE INDEX webhook_events_status_pending ON webhook_events (status, received_at) WHERE status = 'received';

-- Idempotency
CREATE UNIQUE INDEX api_calls_idempotency
  ON api_calls (api_key_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

-- Subscription invariant
CREATE UNIQUE INDEX one_active_sub_per_user
  ON subscriptions (user_id)
  WHERE status IN ('active', 'past_due', 'paused');
```

---

## 8. Constraint summary

```sql
-- Verification ownership
ALTER TABLE verifications ADD CONSTRAINT one_owner
  CHECK ( (user_id IS NOT NULL)::int + (organization_id IS NOT NULL)::int = 1 );

ALTER TABLE verifications ADD CONSTRAINT one_input
  CHECK ( (uploaded_file_id IS NOT NULL)::int + (text_input IS NOT NULL)::int = 1 );

-- File ownership
ALTER TABLE uploaded_files ADD CONSTRAINT one_owner
  CHECK ( (owner_user_id IS NOT NULL)::int + (owner_organization_id IS NOT NULL)::int = 1 );

-- Wallet ownership: exactly one of user / org
ALTER TABLE token_wallets ADD CONSTRAINT one_owner
  CHECK ( (owner_user_id IS NOT NULL)::int + (owner_organization_id IS NOT NULL)::int = 1 );

-- Wallet stays non-negative
ALTER TABLE token_wallets ADD CONSTRAINT non_negative_balance
  CHECK ( balance_bits >= 0 );

-- Ledger deltas are never zero
ALTER TABLE token_ledger_entries ADD CONSTRAINT non_zero_delta
  CHECK ( delta_bits <> 0 );
```

---

## 9. Seed data (run on every fresh DB)

```python
# data migration
Plan.objects.update_or_create(code='free', defaults={
    'name': 'Free',
    'recurring_charge_naira': 0,
    'monthly_grant_bits': 3,                    # TBD — see open Q in 00-platform-plan.md
    'billing_interval': 'none',
    'is_active': True,
})
Plan.objects.update_or_create(code='pro', defaults={
    'name': 'Pro',
    'recurring_charge_naira': 5_000,            # ₦5,000 placeholder — TBD
    'monthly_grant_bits': 50,                   # TBD
    'billing_interval': 'monthly',
    'is_active': True,
})
```

**Conversion rate** lives in Django settings:
```python
# settings.py
BITCHECK_NAIRA_PER_BIT = 100      # ₦100 = 1 bit token  (₦1,000 = 10 bits)
```
Read it once at startup, snapshot per top-up via `top_ups.rate_naira_per_bit`. Move to a `pricing_config` table only when rate changes become user-visible (e.g. tiered org pricing).

---

## 10. Migration & setup notes

1. **Initial migration** enables extensions:
   ```sql
   CREATE EXTENSION IF NOT EXISTS pgcrypto;
   CREATE EXTENSION IF NOT EXISTS citext;
   ```
2. **Custom user model** must be set in `AUTH_USER_MODEL` **before** the first `migrate` runs. Setting it after is a multi-hour rescue mission.
3. **Data migrations** for the `plans` seed should run as a `RunPython` step in the billing app's first migration.
4. **Don't manually edit migration files** after they're applied. Use `makemigrations` / `migrate`. If a schema change is needed, write a new migration.
5. Use Django's `transaction.atomic()` aggressively for any flow that touches `token_wallets` or `subscriptions`.

---

## 11. What's intentionally not modeled (Phase 2+)

- **Team members & roles UI** — schema supports it (`memberships.role`), no UI in hackathon.
- **Webhook delivery to customers** — outbound webhooks for B2B. Not in MVP.
- **Invoice generation** — `subscriptions` has enough info to derive invoices later.
- **PDF report storage** — generate on-demand from `verifications.result_summary` rather than store.
- **Multi-currency** — Squad is NGN-only; no other currency on the roadmap.
- **Refund flows** — `top_ups` has no refund column; add when we hit our first refund case. Bit-token refunds happen via `token_ledger_entries.entry_type = 'refund'`.
- **Org-level subscriptions** — only user-level for now. If a business wants a flat monthly plan that auto-credits bits to the org wallet (instead of bank-transfer top-ups), add `organization_id` to `subscriptions` later. Schema is ready for it.
- **Tiered pricing** — single `BITCHECK_NAIRA_PER_BIT` rate for everyone. If we want enterprise discounts, promote to a `pricing_config` table keyed by org.

---

## 12. Open questions for the backend team

- [ ] **Sessions vs JWT** for auth? Recommendation: Django sessions. Confirm.
- [ ] **Object storage** — S3, R2, MinIO, or backend's existing setup? Affects bucket naming convention.
- [ ] **Celery broker** — Redis is the assumption. Confirm.
- [ ] **File retention** policy — how long do we keep upload blobs after a verification completes? Days? Until user deletes? Tiered by plan?
- [ ] **PII for verification results** — does `result_summary` ever contain user PII (faces, names from documents)? If yes, encryption at rest may be required.
- [ ] **Squad webhook signature** algorithm — Squad sends an HMAC. Document the secret handling and store the HMAC in `webhook_events.signature` for replay/audit.
- [ ] **ML endpoint contract** — does ML push results back via webhook or do we poll? Drives whether `verification_jobs.completed_at` is set by us or by them. Detail in the upcoming `50-backend-integration.md`.
- [ ] **Rate limiting** — at the API gateway or in Django middleware? Affects whether we need a `rate_limit_buckets` table.
- [ ] **Pricing numbers** still TBD per `00-platform-plan.md` § 10 — placeholders are marked `TBD` above. Specifically: free `monthly_grant_bits`, pro `monthly_grant_bits`, pro `recurring_charge_naira`. The conversion rate (`BITCHECK_NAIRA_PER_BIT`) is locked at `100` per the kickoff decision.
- [ ] **Sub-rate transfer policy** — if a B2B org transfers less than `rate_naira_per_bit` to their virtual account, do we credit a partial bit (no — bits are integers), refund the transfer, or hold the credit? Default proposed: insert as `failed`, leave the money in Squad's hands (or refund manually). Confirm.
- [ ] **Bit token rollover for B2C Pro** — current design is "use it or lose it" (period_reset on rollover). If product wants Pro bits to accrue, drop the `period_reset` step from the rollover task.
