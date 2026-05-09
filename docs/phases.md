# Phase Roadmap

**Phase 0: Project Initialization**
* Initialize the core Django project.
* Create all required Django apps using `startapp`: `accounts`, `billing`, `bits`, `api_keys`, `verifications`, `usage`, `webhooks`.
* Configure `settings.py` (database connections, Celery/Redis stubs, REST Framework defaults).

**Phase 1: Identity & Access (`accounts` app)**
* CRITICAL: Do this before any migrations.
* Implement the custom `AUTH_USER_MODEL` (`User`), `Organization`, and `Membership` models. 
* Implement standard Django Session authentication.
* Implement a Google OAuth endpoint (`/api/auth/google/`) that accepts a Google `id_token` from the frontend, uses the `google-auth` Python library to verify it, and then gets or creates the `User` and logs them in via sessions.
* Run the initial `makemigrations` and `migrate`.

**Phase 2: The Financial Core (`bits` app)**
* Implement the unified ledger: `TokenWallet`, `TokenLedgerEntry`, `VirtualAccount`, and `TopUp`.
* Ensure the XOR constraints for B2B vs B2C wallet ownership are enforced at the model level.
* Build the utility functions for safely debiting/crediting wallets using database transactions and row locks.

**Phase 3: B2C Subscriptions (`billing` app)**
* Implement `Plan` and `Subscription` models.
* Write the data migration to seed the 'free' and 'pro' plans.
* Set up the Celery beat task logic for monthly subscription rollovers and token grants.

**Phase 4: B2B API Infrastructure (`api_keys` & `usage` apps)**
* Implement `ApiKey` model (ensure secrets are hashed).
* Implement custom DRF authentication classes for API keys.
* Implement the `ApiCall` model and idempotency logic for tracking business usage.

**Phase 5: Core Verifications (`verifications` app)**
* Implement `UploadedFile` (with S3/storage logic stubs) and `Verification` models.
* Build the core API endpoints for file upload handoffs and verification requests.
* Wire up the Celery tasks to push jobs to the external FastAPI ML service.

**Phase 6: Webhooks (`webhooks` app)**
* Implement the `WebhookEvent` model as an append-only inbox.
* Create the DRF endpoint to receive Squad payment webhooks.
* Write the Celery worker to process these events asynchronously and trigger wallet top-ups.
