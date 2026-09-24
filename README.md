# ensure

A fast, lightweight CLI tool to parse natural language expense/income descriptions and raw bank notifications into structured transactions using a local Apple Silicon LLM (`mlx-lm`) and post them to your finance API (Sure).

---

## Architecture Overview

`ensure` consists of two components:

1. **Local Apple Silicon CLI (`agent/`)**:
   Runs locally on your Mac. Parses natural language phrases or pulls pending bank notifications from the Cloudflare buffer, runs inference using `mlx-community/Qwen3-4B-Instruct-2507-4bit`, resolves categories, accounts, and nature (`income` vs `expense`), and posts to Sure API.

2. **Cloudflare Ingestion Buffer (`cloudflare/`)**:
   A lightweight Cloudflare Worker + D1 (SQLite) database that acts as a secure buffer receiving raw bank/card notifications from iOS Shortcuts (via HTTP POST).
   👉 For complete setup, schema migration, and deployment instructions, see [cloudflare/README.md](cloudflare/README.md).

---

## Features

- **Local LLM Parsing**: Uses `mlx-community/Qwen3-4B-Instruct-2507-4bit` for fast, private, offline extraction.
- **Remote Ingestion Sync (`--sync-transactions`)**: Pulls un-synced banking notifications from Cloudflare D1, parses them with a specialized prompt teaching the model bank SMS structure, and marks them synced upon successful upload to Sure.
- **Income & Expense Detection (`nature`)**: Detects transaction nature (`income` vs `expense`) from both banking notifications (e.g. `PS:+` vs `PS:-`) and natural language phrases (salary, freelance, purchases).
- **Contextual Category Mapping & History Cache (`--cache-history`)**: Caches categories, accounts, and historical sample transactions locally in `.data/` to enrich LLM judgment without repeating API queries.
- **Package-free UV App**: Managed via `pyproject.toml` with fast virtual environments via `uv`.

---

## Prerequisites

- macOS on Apple Silicon (M-series chip)
- [`uv`](https://docs.astral.sh/uv/) package manager
- Python >= 3.14

---

## Configuration (`.env`)

Create or update `.env` in the repository root:

```env
SURE_API_URL="http://sure-web.self-host.orb.local/api/v1/"
SURE_API_KEY="your_api_key_here"
DEFAULT_ACCOUNT_ID="your-default-account-uuid"

# Cloudflare Ingestion Buffer (optional, for --sync-transactions)
CLOUDFLARE_WORKER_URL="https://ensure-worker.<subdomain>.workers.dev"
CLOUDFLARE_AUTH_TOKEN="your_worker_auth_token"
```

> **Note:** Ensure `SURE_API_URL` ends with a trailing slash (`/`).

---

## Global Setup (`ensure` from anywhere)

To run `ensure` from any directory in your terminal, add an alias to `~/.zshrc`:

```bash
alias ensure="uv run --directory /Users/thu4n/repos/ensure python main.py"
```

Reload your shell:
```bash
source ~/.zshrc
```

---

## Usage

```bash
# Parse and post transactions (uses local cache for fast loading)
ensure "200k on new jacket"
ensure "45k banh mi for lunch"
ensure "120k taxi ride yesterday"
ensure "received 500k freelance bonus"

# Input multiple transactions at once (separated by ';')
ensure "45k banh mi ; 30k coffee ; 120k taxi to work"

# Pull and process pending notifications from Cloudflare Worker
ensure --sync-transactions

# Cache transaction history to enrich model judgment
ensure --cache-history
```

---

## Cloudflare Worker Setup

For instructions on deploying the Cloudflare Worker, provisioning D1 SQLite, configuring authentication, and setting up iOS Shortcuts automation, refer to [cloudflare/README.md](cloudflare/README.md).

---

## Managing Dependencies

Because this project uses `uv` with `pyproject.toml`, you can add or remove packages without touching script metadata:

```bash
# Add a dependency
uv add <package-name>

# Remove a dependency
uv remove <package-name>
```

