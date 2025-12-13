# Synthetic DB Generator

Create a synthetic SQLite database for ParseTrail demos/screenshots without real data.

Usage:
```bash
python -m devtools.synthetic.generate_db --output synthetic.db --years 3 --seed 42
```

What it does:
- Builds Accounts, AccountNumbers, Categories, Plugins, Statements, and Transactions via the existing ORM.
- Generates daily activity across checking, savings, credit, and brokerage accounts with synthetic merchants.
- Produces monthly statements and running balances that reconcile.

Notes:
- The script adjusts `sys.path` to import `parsetrail` from `client/src`; run it from the repo root or adjust as needed.
- Outputs are synthetic only; safe for screenshots and sharing.
