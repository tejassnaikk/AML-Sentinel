"""Phase 2: Data Quality gate on Silver. Exit nonzero on any failure (halts pipeline)."""
import sys
import duckdb

SILVER = "silver/transactions_clean.parquet"
MIN_ROWS = 1_000_000
MAX_NULL_PCT = 5.0
REQUIRED = ["tx_id", "ts", "from_account", "to_account", "amount_usd", "is_laundering"]

con = duckdb.connect()
failures = []

# Rule 1: row count
n = con.sql(f"SELECT COUNT(*) FROM '{SILVER}'").fetchone()[0]
if n < MIN_ROWS:
    failures.append(f"row_count: {n:,} < {MIN_ROWS:,}")

# Rule 2: schema
cols = [r[0] for r in con.sql(f"DESCRIBE SELECT * FROM '{SILVER}'").fetchall()]
missing = [c for c in REQUIRED if c not in cols]
if missing:
    failures.append(f"schema: missing columns {missing}")

# Rule 3: nulls on key columns
for c in REQUIRED:
    if c in cols:
        pct = con.sql(
            f'SELECT 100.0 * SUM(("{c}" IS NULL)::INT) / COUNT(*) FROM \'{SILVER}\''
        ).fetchone()[0]
        if pct > MAX_NULL_PCT:
            failures.append(f"nulls[{c}]: {pct:.2f}% > {MAX_NULL_PCT}%")

# Rule 4: amount sanity
bad = con.sql(
    f"SELECT COUNT(*) FROM '{SILVER}' WHERE amount_usd < 0 OR amount_usd > 1e12"
).fetchone()[0]
if bad > 0:
    failures.append(f"amount_sanity: {bad:,} rows negative or > 1e12 USD")

# Rule 5: timestamp range sane (within known dataset window +/- slack)
mn, mx = con.sql(f"SELECT MIN(ts), MAX(ts) FROM '{SILVER}'").fetchone()
if str(mn) < "2022-08-01" or str(mx) > "2022-12-31":
    failures.append(f"ts_range: [{mn}, {mx}] outside expected window")

print(f"DQ gate on {SILVER}: {n:,} rows checked")
if failures:
    print("RESULT: FAIL")
    for f in failures:
        print(f"  ✗ {f}")
    sys.exit(1)
print("RESULT: PASS (all 5 rules)")
