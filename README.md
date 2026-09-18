# ispent

A fast, lightweight CLI tool to parse natural language expense descriptions into structured transactions using a local Apple Silicon LLM (`mlx-lm`) and post them to your finance API.

## Features

- **Local LLM Parsing**: Uses `mlx-community/Llama-3.2-3B-Instruct-4bit` for fast, offline extraction.
- **Contextual Category Mapping**: Uses past transaction examples from each category to provide context to the LLM for accurate categorization.
- **Local Cache & `--update`**: Caches categories, accounts, and category sample transactions locally in `.data/` for near-instant execution, only re-fetching from the API when run with `--update`.
- **Single-File Logic**: All application code lives in `main.py`.
- **Package-free UV App**: Managed via `pyproject.toml` without unnecessary package overhead.

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
SURE_API_TOKEN="your_api_token_here"
DEFAULT_ACCOUNT_ID="your-default-account-uuid"
```

> **Note:** Ensure `SURE_API_URL` ends with a trailing slash (`/`).

---

## Global Setup (`ispent` from anywhere)

To run `ispent` from any directory in your terminal, an alias is added to `~/.zshrc`:

```bash
alias ispent="uv run --directory /Users/thu4n/repos/ispent python main.py"
```

Reload your shell or open a new terminal:
```bash
source ~/.zshrc
```

---

## Usage

You can now run `ispent` from any folder on your laptop:

```bash
# Parse and post transactions (uses local cache for fast loading)
ispent "200k on new jacket"
ispent "45k banh mi for lunch"
ispent "120k taxi ride yesterday"

# Input multiple transactions at once (separated by ';')
ispent "45k banh mi ; 30k coffee ; 120k taxi to work"

# Update local cache (fetches latest accounts, categories, and sample transactions from API)
ispent --update

# You can also update the cache and parse expenses in a single command
ispent --update "45k banh mi for lunch"
```

---

## Managing Dependencies

Because this project uses `uv` with `pyproject.toml`, you can add or remove packages without touching your script metadata:

```bash
# Add a dependency
uv add <package-name>

# Remove a dependency
uv remove <package-name>
```
The global `ispent` launcher will automatically pick up updated dependencies on the next run.
