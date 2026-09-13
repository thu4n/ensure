# ispent

A fast, lightweight CLI tool to parse natural language expense descriptions into structured transactions using a local Apple Silicon LLM (`mlx-lm`) and post them to your finance API.

## Features

- **Local LLM Parsing**: Uses `mlx-community/Llama-3.2-3B-Instruct-4bit` for fast, offline extraction.
- **Dynamic Category Mapping**: Queries the API for categories on the fly and instructs the LLM to match the closest category.
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
ispent "200k on new jacket"
ispent "45k banh mi for lunch"
ispent "120k taxi ride yesterday"
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
