# Bitcheck AI — Backend API

> AI-powered media verification platform that detects manipulated images, AI-generated text, and fraudulent content. Built with Django REST Framework and deployed on Google Cloud Run.

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Django](https://img.shields.io/badge/Django-6.0-092E20?logo=django&logoColor=white)](https://djangoproject.com)
[![DRF](https://img.shields.io/badge/DRF-3.17-A30000?logo=django&logoColor=white)](https://django-rest-framework.org)
[![Cloud Run](https://img.shields.io/badge/Cloud_Run-Deployed-4285F4?logo=googlecloud&logoColor=white)](https://cloud.google.com/run)
[![License](https://img.shields.io/badge/License-Proprietary-red)]()

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Database Setup](#database-setup)
  - [Running Locally](#running-locally)
- [API Endpoints](#api-endpoints)
  - [Authentication](#authentication)
  - [Verification](#verification)
  - [Billing & Token Economy](#billing--token-economy)
  - [B2B Infrastructure](#b2b-infrastructure)
  - [Connectors](#connectors)
- [ML Service Integration](#ml-service-integration)
  - [Image Verification](#image-verification)
  - [Text Verification](#text-verification)
  - [Hash-Based Caching](#hash-based-caching)
  - [Mock Mode](#mock-mode)
- [Token Economy](#token-economy)
- [Payment Integration (Squad)](#payment-integration-squad)
- [Deployment](#deployment)
  - [Docker](#docker)
  - [Google Cloud Run](#google-cloud-run)
- [Documentation](#documentation)
- [Contributing](#contributing)

---

## Overview

**Bitcheck AI** (also known as **ProofChain AI**) is a B2C + B2B verification platform that analyzes media content for authenticity. Users submit images or text and receive AI-driven trust scores, forensic analysis, and fraud detection results in real-time.

### Key Features

- **Image Verification** — Detects AI-generated images, manipulated photos, and deepfakes using forensic analysis, metadata inspection, and ML classification
- **Text Verification** — Identifies AI-generated text, fraud signals, manipulation tactics, and validates factual claims
- **Token Economy** — Bit-based credit system with per-modality pricing (1 bit for text, 2 bits for images)
- **Dual Auth Model** — Session-based auth for the web dashboard (B2C) + HMAC API keys for programmatic access (B2B)
- **Squad Payment Integration** — Card-based subscriptions (B2C) and virtual account top-ups (B2B) via Squad payment gateway
- **Hash-Based Caching** — SHA-256 deduplication skips redundant ML calls for previously analyzed files
- **Connectors** — Third-party integrations (Gmail, Telegram) for automated content verification pipelines
- **Admin Dashboard** — Custom Django admin with dark mode for managing users, verifications, and billing

---

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────────────┐
│   Next.js App    │────▶│  Django REST API │────▶│  ML Services (HF Spaces) │
│   (Frontend)     │◀────│  (This Repo)     │◀────│  Image + Text Endpoints  │
└──────────────────┘     └────────┬─────────┘     └──────────────────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
            ┌────────────┐ ┌──────────┐ ┌─────────────┐
            │ PostgreSQL │ │  Redis   │ │ Squad API   │
            │  (Neon)    │ │ (Upstash)│ │ (Payments)  │
            └────────────┘ └──────────┘ └─────────────┘
```

### Request Flow

1. **Frontend** sends authenticated requests (session cookie or API key)
2. **Django API** validates auth → checks bit balance → computes file hash
3. **Cache check** — if identical file was analyzed before, return cached result
4. **ML Service** — forwards to Hugging Face Spaces for AI analysis
5. **Response** — maps ML output → stores in DB → debits bits → returns JSON

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Runtime** | Python 3.12+ |
| **Framework** | Django 6.0 + Django REST Framework 3.17 |
| **Database** | PostgreSQL (Neon) / SQLite (local dev) |
| **Task Queue** | Celery 5.6 + Redis |
| **Payments** | Squad API (card tokenization + virtual accounts) |
| **ML Services** | Hugging Face Spaces (FastAPI) |
| **Object Storage** | S3-compatible (Cloudflare R2) |
| **Static Files** | Whitenoise (served from Python process) |
| **API Docs** | drf-spectacular (OpenAPI 3.0 / Swagger / ReDoc) |
| **Deployment** | Docker → Google Cloud Run |
| **Auth** | Session (B2C) + HMAC API Keys (B2B) + Google OAuth |

---

## Project Structure

```
bitcheck-backend/
├── config/                      # Project-wide configuration
│   ├── settings.py              # All settings (DB, auth, CORS, Celery, Squad, ML)
│   ├── urls.py                  # Root URL router — connects all app URLs
│   ├── celery.py                # Celery worker configuration
│   └── wsgi.py                  # WSGI entry point for Gunicorn
│
├── apps/
│   ├── core/                    # Structured JSON logger + HTTP middleware
│   ├── accounts/                # Users, organizations, Google OAuth, login/register
│   ├── billing/                 # Plans, subscriptions, Squad card checkout (B2C)
│   ├── bits/                    # Token wallets, ledger, virtual accounts, top-ups (B2B)
│   ├── api_keys/                # B2B API key management (HMAC SHA-256)
│   ├── connectors/              # Third-party integrations (Gmail, Telegram)
│   ├── verifications/           # Core domain — ML verification, caching, results
│   ├── usage/                   # B2B API call logging & analytics
│   └── webhooks/                # External event processing (Squad payment callbacks)
│
├── docs/                        # Documentation
│   ├── system_documentation.md  # Full system architecture reference
│   ├── frontend_integration_guide.md  # Frontend API contract
│   ├── ML_integration/          # ML service integration guides
│   └── Squad_API_Docs/          # Squad payment API reference
│
├── templates/admin/             # Custom Django admin templates (dark mode)
├── Dockerfile                   # Production container (Cloud Run)
├── Dockerfile.worker            # Celery worker container
├── worker_start.py              # Celery worker entry point
├── requirements.txt             # Python dependencies (pinned)
├── .env.example                 # Environment variable template
└── manage.py                    # Django CLI entry point
```

### App Responsibilities

| App | Domain | Key Models |
|---|---|---|
| `accounts` | Identity & access management | `User`, `Organization`, `OrganizationMembership` |
| `billing` | B2C subscription lifecycle | `Plan`, `Subscription` |
| `bits` | Token economy & B2B payments | `TokenWallet`, `TokenLedgerEntry`, `VirtualAccount`, `TopUp` |
| `api_keys` | B2B programmatic access | `ApiKey` |
| `connectors` | Third-party integrations | `ConnectorType`, `ConnectorInstall`, `ConnectorEvent` |
| `verifications` | Core ML verification | `Verification`, `VerificationJob`, `ImageVerificationCache` |
| `usage` | API analytics | `ApiUsageLog` |
| `webhooks` | Payment event processing | *(uses models from bits)* |

---

## Getting Started

### Prerequisites

- **Python 3.12+**
- **PostgreSQL** (or use SQLite for local dev)
- **Redis** (for Celery task queue — optional for basic dev)
- **Git**

### Installation

```bash
# Clone the repository
git clone https://github.com/rightalx/bitcheck-backend.git
cd bitcheck-backend

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables

Copy the template and fill in your values:

```bash
cp .env.example .env
```

**Required variables for local development:**

| Variable | Description | Example |
|---|---|---|
| `SECRET_KEY` | Django signing key | `django-insecure-...` (generate one) |
| `DEBUG` | Debug mode | `True` |
| `ALLOWED_HOSTS` | Allowed hostnames | `localhost,127.0.0.1` |
| `ML_IMAGE_SERVICE_BASE_URL` | Image ML service | `https://jaykay73-bitcheck-image.hf.space` |
| `ML_TEXT_SERVICE_BASE_URL` | Text ML service | `https://jaykay73-bitcheck-text.hf.space` |
| `ML_MOCK_RESPONSE` | Return mock ML results | `True` (set `False` for real ML calls) |

**Optional for full functionality:**

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (leave empty for SQLite) |
| `SQUAD_SECRET_KEY` | Squad API secret key (sandbox) |
| `SQUAD_WEBHOOK_SECRET` | HMAC secret for webhook verification |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `CELERY_BROKER_URL` | Redis URL for Celery |
| `CORS_ALLOWED_ORIGINS` | Frontend origin (e.g., `http://localhost:3000`) |

See [`.env.example`](.env.example) for the complete list with descriptions.

### Database Setup

```bash
# Run migrations
python manage.py migrate

# Create a superuser for Django admin
python manage.py createsuperuser

# (Optional) Collect static files
python manage.py collectstatic --noinput
```

### Running Locally

```bash
# Start the development server
python manage.py runserver

# The API is now available at http://127.0.0.1:8000/
# Admin panel: http://127.0.0.1:8000/admin/
# Swagger docs: http://127.0.0.1:8000/api/docs/
```

**Optional — Start Celery worker** (for async tasks):

```bash
celery -A config worker -l info
```

---

## API Endpoints

### Authentication

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/auth/register/` | Public | Register with email + password |
| `POST` | `/api/auth/login/` | Public | Login (returns session cookie) |
| `POST` | `/api/auth/logout/` | Session | Destroy session |
| `POST` | `/api/auth/google/` | Public | Google OAuth sign-in |
| `GET` | `/api/auth/me/` | Session | Get current user profile |
| `PATCH` | `/api/auth/me/` | Session | Update profile |
| `POST` | `/api/auth/organization/create/` | Session | Create B2B organization |

### Verification

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/verifications/costs/` | Public | Bit costs per modality |
| `POST` | `/api/verifications/verify/image/` | Session | Direct image verification (2 bits) |
| `POST` | `/api/verifications/verify/text/` | Session | Direct text verification (1 bit) |
| `GET` | `/api/verifications/` | Session | List user's verifications (last 50) |
| `GET` | `/api/verifications/<id>/` | Session | Get verification detail + full results |
| `DELETE` | `/api/verifications/` | Session | Soft-delete all verifications |
| `DELETE` | `/api/verifications/<id>/` | Session | Soft-delete a single verification |

### Billing & Token Economy

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/billing/plans/` | Public | List all subscription plans |
| `GET` | `/api/billing/subscription/` | Session | Current subscription + wallet balance |
| `POST` | `/api/billing/subscription/upgrade/` | Session | Initiate Pro upgrade (Squad checkout) |
| `POST` | `/api/billing/subscription/cancel/` | Session | Cancel at period end |
| `GET` | `/api/bits/wallet/` | Session | Org wallet balance + top-up history |
| `POST` | `/api/bits/virtual-account/provision/` | Session | Create Squad virtual account (B2B) |
| `GET` | `/api/bits/virtual-account/` | Session | Get org's virtual account details |

### B2B Infrastructure

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/keys/` | Session | List org's API keys |
| `POST` | `/api/keys/` | Session | Create API key (one-time secret) |
| `POST` | `/api/keys/<id>/revoke/` | Session | Revoke an API key |

### Connectors

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/connectors/types/` | Session | List available connector types |
| `GET/POST` | `/api/connectors/installs/` | Session | List/create connector installs |
| `GET/PATCH/DELETE` | `/api/connectors/installs/<id>/` | Session | Manage a connector install |

### API Documentation

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/docs/` | Swagger UI (interactive) |
| `GET` | `/api/redoc/` | ReDoc (read-only reference) |
| `GET` | `/api/schema/` | OpenAPI 3.0 JSON schema |
| `GET` | `/api/health/` | Health check endpoint |

---

## ML Service Integration

Bitcheck uses two external ML services hosted on Hugging Face Spaces:

| Service | URL | Endpoint | Cost |
|---|---|---|---|
| **Image** | `https://jaykay73-bitcheck-image.hf.space` | `POST /verify/image` | 2 bits |
| **Text** | `https://jaykay73-bitcheck-text.hf.space` | `POST /verify/text` | 1 bit |

### Image Verification

Upload an image via `multipart/form-data` — the backend validates, hashes, and forwards it to the ML service:

```bash
curl -X POST "http://127.0.0.1:8000/api/verifications/verify/image/" \
  -H "Cookie: sessionid=YOUR_SESSION" \
  -F "file=@suspicious_image.jpg" \
  -F "label=audit_report_may2026"
```

**Supported formats:** JPEG, PNG, WEBP — max **12 MB**

**Response includes:**
- `trust_score` (0–100) — overall trust rating
- `verdict` — `authentic` | `inconclusive` | `suspicious` | `manipulated`
- `model_result` — AI/real classification with confidence
- `forensics` — ELA, noise analysis, compression artifacts
- `metadata` — EXIF data, camera info, software flags
- `provenance` — C2PA/content credentials check

### Text Verification

Submit text as JSON — the backend forwards to the text ML service:

```bash
curl -X POST "http://127.0.0.1:8000/api/verifications/verify/text/" \
  -H "Cookie: sessionid=YOUR_SESSION" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "URGENT! Click this link to claim your free grant...",
    "source_url": "http://bit.ly/suspicious-link",
    "context": "WhatsApp broadcast"
  }'
```

**Text limits:** 5–8,000 characters

**Response includes:**
- `trust_score` (0–100) — overall trust rating
- `ai_likelihood` — AI generation detection with confidence
- `fraud_signals` — scam/phishing indicator analysis
- `manipulation_signals` — urgency, emotional manipulation, authority impersonation
- `risk_flags` — list of specific red flags detected
- `source_analysis` — URL reputation check

### Hash-Based Caching

The image verification pipeline includes SHA-256 hash-based caching:

1. Every uploaded file is hashed using **chunked 64KB reads** (memory-safe)
2. The hash is checked against `ImageVerificationCache` in the database
3. **Cache hit** → cached ML result returned instantly (no ML call, ~10ms vs ~5s)
4. **Cache miss** → ML call is made, result is cached for future identical files
5. Bits are **still charged** on cache hits — caching optimizes speed, not cost

Cache hits include `result_summary._cached = true` in the response.

### Mock Mode

When the ML service is down, set `ML_MOCK_RESPONSE=True` in `.env` to return realistic mock responses. Mock responses:
- Still create database records and debit bits
- Include `result_summary._mock = true` in the response
- Use randomized but structurally valid data

---

## Token Economy

Bitcheck uses a **bit-based credit system** where each verification costs a specific number of bits:

| Modality | Cost |
|---|---|
| Text | 1 bit |
| Image | 2 bits |
| Document | 3 bits |
| Audio | 5 bits |
| Video | 8 bits |

### B2C (Consumer) Flow

- **Free plan** → 5 bits on signup
- **Pro plan** → 50 bits per billing cycle (use-it-or-lose-it)
- Bits are debited **only on successful verification** (not on submission)
- On subscription renewal, remaining bits are **reset to 0** before new grant

### B2B (Business) Flow

- Organizations get a **TokenWallet** with a ledger-backed balance
- Top-ups via **Squad Virtual Accounts** (bank transfer → webhook → bit credit)
- Exchange rate: configurable via `BITCHECK_NAIRA_PER_BIT` (default: ₦100/bit)
- API access via HMAC API keys (SHA-256 signed)

### Verdict Mapping

| Trust Score | Verdict | UI Badge |
|---|---|---|
| 86–100 | `authentic` | Green |
| 61–85 | `inconclusive` | Yellow |
| 31–60 | `suspicious` | Orange |
| 0–30 | `manipulated` | Red |

---

## Payment Integration (Squad)

Bitcheck integrates with [Squad](https://squadco.com) for payment processing:

### B2C — Card Subscriptions

1. User initiates Pro upgrade → backend creates a Squad checkout link
2. User completes payment on Squad's hosted page
3. Squad sends webhook → backend activates subscription + grants bits
4. Recurring charges handled by Squad with webhook notifications

### B2B — Virtual Account Top-Ups

1. Admin provisions a dedicated virtual account via Squad API
2. Client transfers funds to the virtual account (bank transfer)
3. Squad sends webhook with transaction details
4. Backend converts NGN → bits and credits the organization's wallet

### Webhook Security

- **Card webhooks** → verified via `X-Squad-Encrypted-Body` HMAC header
- **VA webhooks** → verified via `encrypted_body` field in the payload
- Idempotent processing — duplicate webhooks are safely ignored

---

## Deployment

### Docker

```bash
# Build the image
docker build -t bitcheck-api .

# Run (requires env file + external DB/Redis)
docker run --rm -p 8080:8080 \
  -e PORT=8080 \
  --env-file .env \
  bitcheck-api
```

### Google Cloud Run

The production deployment uses Google Cloud Build + Cloud Run:

```bash
# Submit build to Cloud Build
gcloud builds submit --tag gcr.io/PROJECT_ID/bitcheck-api

# Deploy to Cloud Run
gcloud run deploy bitcheck-api \
  --image gcr.io/PROJECT_ID/bitcheck-api \
  --platform managed \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars "KEY=VALUE"
```

**Production environment:**
- **Runtime:** Google Cloud Run (containerized, stateless)
- **Database:** PostgreSQL on Neon (pooled connection)
- **Cache/Queue:** Redis on Upstash
- **Static files:** Whitenoise (baked into Docker image at build time)
- **Workers:** Separate Cloud Run service running `Dockerfile.worker`

---

## Documentation

| Document | Description |
|---|---|
| [`docs/system_documentation.md`](docs/system_documentation.md) | Full system architecture reference — app breakdown, data flows, security decisions |
| [`docs/frontend_integration_guide.md`](docs/frontend_integration_guide.md) | Complete API contract for frontend integration — request/response examples, error handling |
| [`docs/ML_integration/`](docs/ML_integration/) | ML service integration guides (image + text APIs) |
| [`docs/Squad_API_Docs/`](docs/Squad_API_Docs/) | Squad payment API reference (virtual accounts, webhooks) |
| `/api/docs/` | Interactive Swagger UI (live, when server is running) |
| `/api/redoc/` | ReDoc API reference (live, when server is running) |

---

## Contributing

1. **Create a branch** from `main`
2. **Follow the app pattern** — models → serializers → services → views → urls
3. **Keep views thin** — business logic belongs in `services.py`
4. **Add migrations** — always run `python manage.py makemigrations` after model changes
5. **Test locally** — verify with `python manage.py runserver` before pushing
6. **Environment** — never commit `.env` files; update `.env.example` for new variables

---

<p align="center">
  <strong>Bitcheck AI</strong> — Verify what's real. Protect what matters.
  <br>
  <sub>Built by Team 4Bits · 2026</sub>
</p>
