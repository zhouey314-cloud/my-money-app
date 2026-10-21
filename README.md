# My Money App — legacy local experiment

This is a personal text-to-expense prototype, **not a financial adviser or a
production accounting system**. Phone dictation is supplied by the keyboard;
this app does not transcribe audio. A model may misread an amount or category:
schema validation does not verify that its interpretation is correct.

## Offline checks (Python 3.11+; no packages or API key)

```sh
python3 -m unittest discover -s tests -v
python3 ledger.py check --path /your/local/my_expenses.csv
```

Tests only create clearly synthetic records in temporary directories. They
cover JSON types, duplicate keys, non-finite/negative amounts, spreadsheet
formulas, invalid dates, duplicate saves, corrupted CSV, replacement failure,
backups, concurrent writes, symlinks and non-destructive migration. No personal
ledger, model API, credentials or financial extraction accuracy is tested.

## Optional UI

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py --server.address 127.0.0.1
```

The dependency versions are the local verification versions, not a claim of a
complete transitive lock or security certification. Only the configured model
service receives the text after the user clicks the button. No key is committed
or logged; provider exceptions are replaced with a generic error. Real service
requests and human-reviewed extraction accuracy remain **NOT_TESTED**.

The unchanged prompt requests `item`, numeric `amount`, one of the existing
seven Chinese categories and `currency`. The offline guard accepts positive,
finite amounts with at most two decimal places and a three-uppercase-letter
currency format (not a full ISO currency registry). The application supplies
the recorded date, rather than trusting a model-supplied date. Different
currencies are shown separately, with no invented exchange rate.

## Existing CSV, backup and recovery

- The existing five-column schema is retained: `item,amount,category,currency,date`.
  Existing column order may differ; dates must be `YYYY-MM-DD HH:MM`.
- Validation happens before a save. A malformed file is refused and preserved;
  it is never replaced by an empty ledger. A successful append first creates a
  byte-for-byte, mode-0600 backup, then atomically replaces the CSV with a
  mode-0600 file under a macOS/Linux advisory lock.
- An identical normalized record in the same minute is refused by default.
  Two genuine identical purchases require the explicit UI confirmation option.
  This is a conservative duplicate guard, not transaction-ID reconciliation.
- `python3 ledger.py backup --path /your/local/my_expenses.csv` preserves even
  a damaged file. Neither backup nor check prints expense values.
- `python3 ledger.py migrate-copy --path /your/local/my_expenses.csv --output /your/local/checked-copy.csv`
  creates a **new** validated copy and never overwrites either the source or
  an existing destination. There is no automatic migration on startup.
- To recover, stop the UI, make a backup of the current file, and check a chosen
  backup with `ledger.py check` before explicitly copying it back. Keep the
  original until the restored copy has been inspected. No automatic restore or
  deletion is performed. Backups contain private data and need local retention
  and storage protection.

Windows locking, power-loss durability, hostile users with control of the data
directory, large-ledger scalability and real financial data migration remain
NOT_TESTED. `.gitignore` covers CSVs/backups, local databases, env and test output;
it does not remove anything already committed. Do not upload a ledger or backup.
No license grant is added to this legacy repository.
