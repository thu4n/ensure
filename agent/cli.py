from collections import defaultdict
from datetime import datetime
import json
import sys
from mlx_lm import load

from agent.api import (
    cache_history,
    create_transaction_import,
    fetch_account_detail,
    fetch_pending_transactions,
    fetch_uncategorized_transactions,
    load_data,
    mark_transactions_synced,
    update_cached_account_balance,
    update_transaction_category,
    wait_for_import_completion,
)
from agent.config import CLOUDFLARE_WORKER_URL, MODEL_ID
from agent.extractor import (
    categorize_transaction,
    extract_notification_details,
    extract_transaction_details,
)
from agent.resolver import (
    build_import_csv,
    build_import_row,
    resolve_account_id,
    resolve_category_id,
)


def print_usage():
    print('Usage: ensure [options] ["<expense sentence>"]')
    print("\nOptions:")
    print("  --sync-transactions, -s  Fetch and process pending transactions from Cloudflare Worker")
    print("  --categorize, -c         Categorize any uncategorized transactions in Sure using local LLM")
    print("  --cache-history          Cache categories, accounts, rules, and history samples")
    print("  --help, -h               Show this help message")
    print("\nExamples:")
    print('  ensure "45k banh mi for lunch"')
    print('  ensure "45k banh mi ; 30k coffee"')
    print("  ensure --sync-transactions")
    print("  ensure --categorize")
    print("  ensure --cache-history")


def main():
    raw_args = sys.argv[1:]
    sync_flag = False
    categorize_flag = False
    cache_history_flag = False
    filtered_args = []

    for arg in raw_args:
        if arg in ("--sync-transactions", "-s"):
            sync_flag = True
        elif arg in ("--categorize", "-c"):
            categorize_flag = True
        elif arg == "--cache-history":
            cache_history_flag = True
        elif arg in ("--help", "-h"):
            print_usage()
            sys.exit(0)
        else:
            filtered_args.append(arg)

    if not sync_flag and not categorize_flag and not cache_history_flag and not filtered_args:
        print_usage()
        sys.exit(1)

    if cache_history_flag:
        cache_history()
        if not sync_flag and not categorize_flag and not filtered_args:
            return

    category_map, account_map, category_samples = load_data()

    items_to_process: list[tuple[str, str | None, str | None]] = []

    if sync_flag:
        print(f"Connecting to Cloudflare Worker ({CLOUDFLARE_WORKER_URL or 'not configured'})...")
        try:
            pending = fetch_pending_transactions()
            print(f"Retrieved {len(pending)} pending item(s) from remote buffer.")
            for item in pending:
                raw_text = (item.get("raw") or "").strip()
                if raw_text:
                    items_to_process.append((raw_text, item.get("id"), item.get("created_at")))
        except Exception as e:
            print(f"Error fetching from Cloudflare Worker: {e}", file=sys.stderr)
            sys.exit(1)

    raw_input = " ".join(filtered_args).strip()
    if raw_input:
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item in raw_input.split(";"):
            tx = item.strip()
            if tx:
                items_to_process.append((tx, None, now_ts))

    if not items_to_process and not categorize_flag:
        if sync_flag:
            print("No pending transactions to process.")
            return
        print_usage()
        sys.exit(1)

    model = None
    tokenizer = None
    mismatches: list[dict] = []
    imported_dates: list[str] = []
    imported_account_ids: set[str] = set()
    extract_success_count = 0
    total = len(items_to_process)

    # =========================================================================
    # PHASE 1: Extract Transactions & Create Sure Import (Rules Run Natively)
    # =========================================================================
    if items_to_process:
        print(f"\n[Phase 1] Extracting {total} transaction(s). Loading local LLM ({MODEL_ID})...")
        model, tokenizer = load(MODEL_ID)

        grouped_imports: dict[str, list[dict]] = defaultdict(list)
        fetched_live_accounts: set[str] = set()

        for idx, (raw_text, cf_id, tx_timestamp) in enumerate(items_to_process, start=1):
            prefix = f"[{idx}/{total}] " if total > 1 else ""
            print(f'\n{prefix}Parsing: "{raw_text}"...')

            try:
                if cf_id or "\n" in raw_text or "PS:" in raw_text:
                    parsed = extract_notification_details(
                        raw_text,
                        category_map,
                        account_map,
                        category_samples,
                        timestamp=tx_timestamp,
                        model=model,
                        tokenizer=tokenizer,
                    )
                else:
                    parsed = extract_transaction_details(
                        raw_text,
                        category_map,
                        account_map,
                        category_samples,
                        timestamp=tx_timestamp,
                        model=model,
                        tokenizer=tokenizer,
                    )
                print(f"Parsed by LLM:\n{json.dumps(parsed, indent=2, ensure_ascii=False)}")

                acc_name = parsed.get("account")
                acc_id = resolve_account_id(acc_name, account_map) if acc_name else resolve_account_id("", account_map)
                acc_info = account_map.get(acc_name) if acc_name else None
                if not acc_info and acc_id:
                    for k, v in account_map.items():
                        if isinstance(v, dict) and v.get("id") == acc_id:
                            acc_info = v
                            acc_name = k
                            break

                # Verify running balance if present (depository / checking / savings accounts only)
                is_credit = acc_info and acc_info.get("account_type") == "credit_card"
                if "running_balance" in parsed and acc_name and not is_credit:
                    bank_balance = parsed["running_balance"]
                    curr_balance = None

                    # Fetch live balance from Sure once per account at the start of the batch
                    if acc_id and acc_id not in fetched_live_accounts:
                        try:
                            live_acc = fetch_account_detail(acc_id)
                            curr_balance = live_acc.get("balance_cents")
                            fetched_live_accounts.add(acc_id)
                            if acc_info and curr_balance is not None:
                                acc_info["balance_cents"] = curr_balance
                        except Exception as e:
                            print(f"Notice: Live balance lookup skipped ({e}). Using cached balance.", file=sys.stderr)

                    if curr_balance is None and acc_info:
                        curr_balance = acc_info.get("balance_cents")

                    if curr_balance is not None:
                        tx_amount = parsed.get("amount", 0)
                        tx_nature = parsed.get("nature", "expense")
                        delta = tx_amount if tx_nature == "income" else -tx_amount
                        expected_balance = curr_balance + delta
                        discrepancy = bank_balance - expected_balance

                        curr_code = parsed.get("currency") or (acc_info.get("currency") if acc_info else "VND") or "VND"

                        if discrepancy != 0:
                            mismatch_msg = (
                                f"[⚠️ Balance Mismatch: Bank reported {bank_balance:,} {curr_code}, "
                                f"Sure expected {expected_balance:,} {curr_code} (diff: {discrepancy:+,} {curr_code})]"
                            )
                            existing_notes = parsed.get("notes") or ""
                            parsed["notes"] = f"{existing_notes}\n{mismatch_msg}".strip() if existing_notes else mismatch_msg

                            print(
                                f"\n⚠️  BALANCE MISMATCH for '{acc_name}':\n"
                                f"   Bank reported (SD): {bank_balance:,} {curr_code}\n"
                                f"   Sure expected:      {expected_balance:,} {curr_code}\n"
                                f"   Discrepancy:        {discrepancy:+,} {curr_code}\n"
                                f"   → Attached note to transaction in Sure for investigation."
                            )
                            mismatches.append({
                                "account": acc_name,
                                "bank": bank_balance,
                                "expected": expected_balance,
                                "diff": discrepancy,
                                "currency": curr_code,
                                "tx_name": parsed.get("name") or raw_text[:30],
                            })
                        else:
                            print(f"✓ Balance verified: {bank_balance:,} {curr_code} matches Sure ledger.")

                # Advance in-memory account balance for subsequent items in the same batch
                if acc_name and acc_info:
                    if "running_balance" in parsed:
                        acc_info["balance_cents"] = parsed["running_balance"]
                    elif parsed.get("amount") and acc_info.get("balance_cents") is not None:
                        delta = parsed["amount"] if parsed.get("nature") == "income" else -parsed["amount"]
                        acc_info["balance_cents"] += delta

                row = build_import_row(parsed, account_map)
                row["cf_id"] = cf_id
                row["account_name"] = acc_name
                row["running_balance"] = parsed.get("running_balance")
                row["raw_delta"] = (
                    parsed.get("amount", 0)
                    if parsed.get("nature") == "income"
                    else -parsed.get("amount", 0)
                )
                grouped_imports[row["account_id"]].append(row)
                extract_success_count += 1

            except Exception as e:
                print(f'Error extracting "{raw_text}": {e}', file=sys.stderr)

        # Submit one CSV import per account so Sure's native rules run automatically
        import_success_count = 0
        for acc_id, rows in grouped_imports.items():
            acc_label = rows[0].get("account_name") or acc_id
            csv_content = build_import_csv(rows)
            print(f"\nCreating Sure import for account '{acc_label}' ({len(rows)} row(s))...")
            print(csv_content.strip())

            try:
                imp_res = create_transaction_import(acc_id, csv_content)
                imp_data = imp_res.get("data", {})
                imp_id = imp_data.get("id")
                print(f"Import created (ID: {imp_id}, status: {imp_data.get('status')}). Waiting for processing & rules...")

                if imp_id:
                    final_imp = wait_for_import_completion(imp_id)
                    print(f"✓ Import {imp_id} completed (status: {final_imp.get('status')}).")

                imported_account_ids.add(acc_id)
                for r in rows:
                    if r.get("date"):
                        imported_dates.append(r["date"])
                    if r.get("account_name"):
                        if r.get("running_balance") is not None:
                            update_cached_account_balance(r["account_name"], new_balance_cents=r["running_balance"])
                        elif r.get("raw_delta"):
                            update_cached_account_balance(r["account_name"], delta_cents=r["raw_delta"])

                cf_ids = [r["cf_id"] for r in rows if r.get("cf_id")]
                if cf_ids:
                    mark_transactions_synced(cf_ids)
                    print(f"Acknowledged sync in Cloudflare D1 for {len(cf_ids)} ID(s): {cf_ids}")

                import_success_count += len(rows)
            except Exception as e:
                print(f"Error importing transactions for account '{acc_label}': {e}", file=sys.stderr)

        if total > 1 or sync_flag:
            print(f"\nPhase 1 Completed: {import_success_count}/{total} transaction(s) imported into Sure.")

    # =========================================================================
    # PHASE 2: Pull Uncategorized Transactions & Categorize with Local LLM
    # =========================================================================
    if imported_dates or categorize_flag:
        start_date = min(imported_dates) if imported_dates else None
        end_date = max(imported_dates) if imported_dates else None
        acc_filter = list(imported_account_ids) if imported_account_ids and not categorize_flag else None

        print("\n[Phase 2] Checking Sure for uncategorized transactions...")
        try:
            uncategorized = fetch_uncategorized_transactions(
                start_date=start_date,
                end_date=end_date,
                account_ids=acc_filter,
            )
        except Exception as e:
            print(f"Error fetching uncategorized transactions: {e}", file=sys.stderr)
            uncategorized = []

        if not uncategorized:
            print("✓ No uncategorized transactions remaining (all handled by Sure rules).")
        else:
            print(f"Found {len(uncategorized)} uncategorized transaction(s). Running local LLM categorization...")
            if model is None or tokenizer is None:
                print(f"Loading local LLM ({MODEL_ID})...")
                model, tokenizer = load(MODEL_ID)

            cat_success = 0
            for idx, tx in enumerate(uncategorized, start=1):
                tx_id = tx.get("id")
                tx_name = tx.get("name", "Unknown")
                tx_amount = tx.get("amount", "")
                tx_date = tx.get("date", "")
                print(f'  [{idx}/{len(uncategorized)}] Categorizing: "{tx_name}" ({tx_amount} on {tx_date})...')
                try:
                    cat_name = categorize_transaction(
                        tx,
                        category_map=category_map,
                        category_samples=category_samples,
                        model=model,
                        tokenizer=tokenizer,
                    )
                    cat_id = resolve_category_id(cat_name, category_map)
                    if not cat_id:
                        print(f"    ⚠️ Could not resolve category ID for '{cat_name}', skipping.", file=sys.stderr)
                        continue
                    update_transaction_category(tx_id, cat_id)
                    print(f'    ✓ Assigned category: "{cat_name}"')
                    cat_success += 1
                except Exception as e:
                    print(f'    Error categorizing "{tx_name}": {e}', file=sys.stderr)

            print(f"Phase 2 Completed: {cat_success}/{len(uncategorized)} uncategorized transaction(s) categorized.")

    if mismatches:
        print("\n" + "=" * 65)
        print("⚠️  BALANCE MISMATCH SUMMARY (Requires Investigation):")
        for m in mismatches:
            print(
                f"  • {m['account']} (\"{m['tx_name']}\"): "
                f"Bank reported {m['bank']:,} {m['currency']} vs Sure expected {m['expected']:,} {m['currency']} "
                f"(diff: {m['diff']:+,} {m['currency']})"
            )
        print("=" * 65)

    if items_to_process and (total > 1 or sync_flag) and extract_success_count < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
