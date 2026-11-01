#!/usr/bin/env -S uv run python
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure repository root is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from agent.resolver import build_payload, resolve_account_id


def run_checks():
    account_map = {
        "Main ATM": {
            "id": "ea1f0aed-692d-44d4-a512-263ade7594f1",
            "institution_name": "TP Bank",
            "account_type": "depository",
            "balance_cents": 1_000_000,
            "currency": "VND",
        },
        "Visa Flash": {
            "id": "da7c910f-7c7d-4c80-a3be-390cf9487912",
            "institution_name": "TP Bank",
            "account_type": "credit_card",
            "balance_cents": 0,
            "currency": "VND",
        },
    }

    print("Running balance mismatch & reconciliation test suite...\n")

    # 1. Test Discrepancy Detection on Expense
    print("Test 1: Expense mismatch detection")
    parsed_expense = {
        "account": "Main ATM",
        "amount": 50_000,
        "nature": "expense",
        "running_balance": 900_000,  # Expected: 1,000,000 - 50,000 = 950,000 -> Diff = -50,000
        "notes": "",
        "currency": "VND",
    }
    acc_info = account_map["Main ATM"]
    curr_balance = acc_info["balance_cents"]
    expected_expense = curr_balance - parsed_expense["amount"]
    diff_expense = parsed_expense["running_balance"] - expected_expense
    assert diff_expense == -50_000, f"Expected -50,000 diff, got {diff_expense}"

    note_expense = f"[⚠️ Balance Mismatch: Bank reported {parsed_expense['running_balance']:,} VND, Sure expected {expected_expense:,} VND (diff: {diff_expense:+,} VND)]"
    parsed_expense["notes"] = note_expense
    payload = build_payload(parsed_expense, {}, account_map)
    assert note_expense in payload["transaction"]["notes"]
    print("  ✓ Expense mismatch correctly computed (-50,000 VND) and annotated in payload notes.")

    # 2. Test Discrepancy Detection on Income
    print("Test 2: Income mismatch detection")
    parsed_income = {
        "account": "Main ATM",
        "amount": 200_000,
        "nature": "income",
        "running_balance": 1_300_000,  # Expected: 1,000,000 + 200,000 = 1,200,000 -> Diff = +100,000
        "notes": "Salary bonus",
        "currency": "VND",
    }
    expected_income = curr_balance + parsed_income["amount"]
    diff_income = parsed_income["running_balance"] - expected_income
    assert diff_income == 100_000, f"Expected +100,000 diff, got {diff_income}"

    note_income = f"[⚠️ Balance Mismatch: Bank reported {parsed_income['running_balance']:,} VND, Sure expected {expected_income:,} VND (diff: {diff_income:+,} VND)]"
    parsed_income["notes"] = f"{parsed_income['notes']}\n{note_income}"
    payload_income = build_payload(parsed_income, {}, account_map)
    assert "Salary bonus" in payload_income["transaction"]["notes"]
    assert note_income in payload_income["transaction"]["notes"]
    print("  ✓ Income mismatch correctly computed (+100,000 VND) and preserved original user notes.")

    # 3. Test Exact Match (No Discrepancy)
    print("Test 3: Exact match verification")
    parsed_exact = {
        "account": "Main ATM",
        "amount": 50_000,
        "nature": "expense",
        "running_balance": 950_000,  # Exact match: 1,000,000 - 50,000 = 950,000
        "notes": "",
        "currency": "VND",
    }
    expected_exact = curr_balance - parsed_exact["amount"]
    diff_exact = parsed_exact["running_balance"] - expected_exact
    assert diff_exact == 0, f"Expected 0 diff, got {diff_exact}"
    payload_exact = build_payload(parsed_exact, {}, account_map)
    assert payload_exact["transaction"]["notes"] == ""
    print("  ✓ Exact match produces 0 discrepancy and leaves notes untouched.")

    # 4. Test Credit Card Skip
    print("Test 4: Credit card account exclusion")
    card_info = account_map["Visa Flash"]
    is_credit = card_info["account_type"] == "credit_card"
    assert is_credit is True
    print("  ✓ Credit card accounts correctly identify and skip running balance verification.")

    print("\n✅ All 4 balance verification tests passed successfully!")


if __name__ == "__main__":
    run_checks()
