# Bitcheck AI — Implementation Backlog

> **Last audited:** 2026-05-11 against the live Django codebase.
> Items listed here are features that are **designed in the spec but not yet implemented**.
> ~~Struck-through~~ items have been completed since the last audit.

---

## Critical Path (Blocks Frontend)

### 1. Presigned URL Endpoint for File Uploads
- **What:** `POST /api/verifications/upload-url/` — generates a presigned S3 PUT URL and creates the `UploadedFile` row.
- **Why missing:** Requires live S3/MinIO credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_ENDPOINT_URL`). The `UploadedFile` model is fully implemented, but the view + boto3 presigned URL generation code was not built because there's no object storage to test against.
- **Blocks:** All file-based verifications (image, video, audio, document). Text verifications work today.
- **Effort:** ~1 hour once S3/MinIO is provisioned.
- **Files to create/modify:**
  - `apps/verifications/views.py` — add `upload_url_view()`
  - `apps/verifications/urls.py` — add `path('upload-url/', ...)`

### ~~2. Pro Plan Upgrade Flow (Squad Checkout Initiation)~~ ✅ DONE
- **Built in:** `apps/billing/views.py` → `upgrade_subscription_view`, `apps/billing/services.py` → `initiate_pro_checkout`
- **Endpoints:** `POST /api/billing/subscription/upgrade/`, `POST /api/billing/subscription/cancel/`
- **Card tokenization** via Squad's `is_recurring: true` flag. Webhook handler stores `squad_card_token_id` for recurring charges.

---

## Important (Does Not Block MVP Demo)

### ~~3. B2B Virtual Account Provisioning Endpoint~~ ✅ DONE
- **Built in:** `apps/bits/views.py`, `apps/bits/va_services.py`, `apps/bits/urls.py`
- **Endpoints:** `POST /api/bits/virtual-account/provision/`, `GET /api/bits/virtual-account/`, `GET /api/bits/wallet/`
- **Dev mock mode:** `SQUAD_VA_DEV_MOCK=True` creates local VA rows without calling Squad (for demos when sandbox isn't profiled for B2B).
- **Webhook handler:** `apps/webhooks/services.py` → `_handle_virtual_account_credit()` converts naira bank transfers to bits.

### 4. Organization Management Endpoints (Invite, Roles, etc.)
- **What:** Invite members, manage roles (admin/member/viewer), list members, remove members.
- **Partially done:** Organization creation now happens automatically during B2B registration (`POST /api/auth/register/` with `account_type: "organization"`, `organization_name`, `organization_description`). The `Organization` and `Membership` models are fully implemented.
- **Still missing:** Invite-by-email, role change, member removal, org settings update.
- **Blocks:** B2B self-service team management. Can be done via Django admin for the demo.
- **Effort:** ~2 hours.

### 5. B2B Verification Submission Endpoint
- **What:** `POST /api/v1/verifications` authenticated via `Bearer bk_live_*` API key (not session). The `submit_b2b_verification()` service function exists and works; it just doesn't have an HTTP view wired to it.
- **Why missing:** The B2B auth layer (`ApiKeyAuthentication`) is built and tested, and the B2B submission service is implemented. The missing piece is the actual DRF view that ties them together.
- **Blocks:** B2B API usage (customers calling the verification API programmatically).
- **Effort:** ~30 minutes. Wire `ApiKeyAuthentication` to a new view that calls `submit_b2b_verification()`.

### 6. API Usage Logs Endpoint (B2B Dashboard)
- **What:** `GET /api/usage/` — list `ApiCall` records for an organization, filterable by date range, api_key, modality.
- **Why missing:** The `ApiCall` model and logging services (`log_api_call`, `check_idempotency`) are implemented but there's no user-facing endpoint to query them. `apps/usage/views.py` is still the default Django stub.
- **Blocks:** B2B usage analytics dashboard. Data is visible in Django admin.
- **Effort:** ~1 hour.

---

## Nice-to-Have (Post-Hackathon)

### 7. XOR Input Constraint on Verification Model
- **What:** A DB-level `CHECK` constraint ensuring exactly one of `uploaded_file_id` or `text_input` is set on each verification.
- **Why missing:** SQLite doesn't support the needed `CHECK` syntax with `IS NOT NULL` casts. Currently enforced at the application layer (serializer + service).
- **Action:** Add via a PostgreSQL-only migration when switching to production DB.

### 8. Audit Log System
- **What:** `audit_logs` table tracking user actions (`api_key.created`, `subscription.canceled`, etc.) per design doc § 4.9.
- **Status:** Marked as "stretch" in the design doc. Not implemented.
- **Effort:** ~2 hours for model + middleware.

### 9. Outbound Webhooks for B2B Customers
- **What:** Notify B2B customers when their verification completes via a webhook to their configured URL.
- **Status:** Not in the hackathon scope per design doc § 11.

### 10. PDF Report Generation
- **What:** Generate downloadable verification reports from `result_summary`.
- **Status:** Design doc says "generate on-demand, don't store." Not implemented.

### 11. WebSocket for Real-Time Verification Status
- **What:** Replace polling with WebSocket push when a verification completes.
- **Status:** Currently using 3-second polling. WebSocket would require Django Channels.

---

## Environment Dependencies

These items are implemented in code but require external services to be provisioned:

| Dependency | Env Vars Needed | What It Unblocks |
|---|---|---|
| S3/MinIO | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_ENDPOINT_URL` | File uploads (#1) |
| Squad API (B2B profiling) | `SQUAD_SECRET_KEY` + Squad sandbox B2B profiling enabled | Virtual account provisioning (workaround: `SQUAD_VA_DEV_MOCK=True`) |
| Redis | `REDIS_URL` | Celery tasks (verification processing, subscription rollover, webhook retry) |
| ML/FastAPI service | `ML_SERVICE_BASE_URL` (running service) | Actual verification analysis results |
