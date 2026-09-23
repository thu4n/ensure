# ensure-worker (Cloudflare Ingestion Buffer)

A lightweight buffer Worker that receives raw bank and card SMS from your phone, stores them in Cloudflare D1 (SQLite), and exposes simple endpoints for your local Mac CLI (`ensure`) to pull, extract with local LLM, and post to Sure.

---

## 1. Cloudflare D1 Setup

### Step 1: Create the D1 Database

```bash
pnpm wrangler d1 create ensure-db
```

This will print a snippet with your `database_id`. Paste it into `wrangler.jsonc`:

```jsonc
"d1_databases": [
  {
    "binding": "DB",
    "database_name": "ensure-db",
    "database_id": "<YOUR_D1_DATABASE_ID>"
  }
]
```

### Step 2: Initialize the Table Schema

Run the SQL migration to create the `transactions` table:

```bash
# For local testing:
pnpm wrangler d1 execute ensure-db --local --file=./schema.sql

# For remote / production:
pnpm wrangler d1 execute ensure-db --remote --file=./schema.sql
```

*(Note: The Worker also auto-initializes the table via `CREATE TABLE IF NOT EXISTS` if not already created).*

---

## 2. Authentication (API Secret Token)

To protect your endpoints, configure an `AUTH_TOKEN`:

- **Production (Cloudflare Dashboard):**
  Worker $\rightarrow$ **Settings** $\rightarrow$ **Variables and Secrets** $\rightarrow$ **Add** $\rightarrow$ Choose **Secret** $\rightarrow$ Name: `AUTH_TOKEN`.
  *(Or run `pnpm wrangler secret put AUTH_TOKEN`)*

- **Local Dev:**
  Create `.dev.vars` in `cloudflare/`:
  ```env
  AUTH_TOKEN=your-secret-token
  ```

### How to Authenticate Requests

Send the token via the `Authorization` header:
```bash
curl -H "Authorization: Bearer <AUTH_TOKEN>" https://<worker>.<subdomain>.workers.dev/pending
```

*(Or via query parameter fallback for phone shortcuts: `?token=<AUTH_TOKEN>`)*

---

## 3. API Endpoints

### 1. Ingest notification (Phone)
- **Method:** `POST /` or `POST /ingest`
- **Body:** Raw text from the banking app's notification.
- **Behavior:** Hashes content to deduplicate retries, inserts with `synced = 0`.
- **Response:** `{"status": "received", "id": "4a2f8b..."}`

### 2. Pull Pending Transactions (Local Mac)
- **Method:** `GET /pending`
- **Behavior:** Returns all items where `synced = 0` ordered by oldest first.
- **Response:**
  ```json
  [
    {
      "id": "4a2f8b...",
      "raw": "(TPBank): 22/09/26;19:55\nTK: xxxx...",
      "created_at": "2026-09-23 12:30:00"
    }
  ]
  ```

### 3. Acknowledge Sync (Local Mac)
- **Method:** `POST /sync`
- **Body:**
  ```json
  { "ids": ["4a2f8b..."] }
  ```
- **Behavior:**
  - Marks specified transactions as `synced = 1`.
  - Automatically cleans up synced transactions older than 14 days.
  - **Never deletes unsynced items.**

---

## 4. Local Development & Deployment

```bash
# Start local dev server (uses local SQLite simulation)
pnpm dev

# Deploy to Cloudflare
pnpm deploy
```

---

## 5. Privacy & Data Security

Cloudflare does **not** inspect, read, or train AI models on customer data stored in D1. Cloudflare acts strictly as an infrastructure provider under standard data processing agreements, and data in D1 is encrypted at rest (AES-256) and in transit (TLS).
