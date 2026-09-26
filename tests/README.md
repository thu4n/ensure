# Test Suite

A standalone testing harness to test the LLM extraction capability offline without pulling from Cloudflare or posting to Sure API.

---

## Directory Structure

```
tests/
  ├── README.md                  # This documentation
  ├── test_extraction.py         # Test runner script
  └── data/                      # Test samples directory
      ├── sample_expense.txt     # Simple natural language expense sample
      ├── sample_atm.txt         # Generic ATM notification sample
      ├── sample_credit_card.txt # Generic credit card notification sample
      └── *.local.txt            # Your private local samples (ignored by git)
```

---

## Adding New Test Data

### Public / Committed Samples
Add sanitized files without real account numbers or personal details:
- `tests/data/sample_salary.txt`
- `tests/data/sample_transfer.txt`

### Private Real SMS Samples (Never Tracked by Git)
To test with your real, unredacted banking SMS without committing personal financial info, name your file with `.local.txt`:
- `tests/data/my_checking.local.txt`
- `tests/data/my_credit_card.local.txt`

Files matching `*.local.txt` and `tests/data/private/` are `.gitignore`d.

---

## Running Tests

### 1. Run all test files in `tests/data/`:
```bash
uv run python tests/test_extraction.py
```

### 2. Run a specific test file:
```bash
uv run python tests/test_extraction.py tests/data/sample_credit_card.txt
```

### 3. Run with inline raw text:
```bash
uv run python tests/test_extraction.py "(BankName): 24/09/26;08:30 TK: xxxx1234 PS:-50.000VND ND: ca phe sang"
```
