"""Phase 0: inspect the raw IBM AML HI-Small dataset — schema, volume, labels, patterns."""
import duckdb

TRANS = "data/raw/HI-Small_Trans.csv"
PATTERNS = "data/raw/HI-Small_Patterns.txt"

con = duckdb.connect()

print("=" * 60)
print("SCHEMA (as inferred by DuckDB)")
print("=" * 60)
print(con.sql(f"DESCRIBE SELECT * FROM read_csv_auto('{TRANS}')"))

print("=" * 60)
print("ROW COUNT")
print("=" * 60)
print(con.sql(f"SELECT COUNT(*) AS rows FROM read_csv_auto('{TRANS}')"))

print("=" * 60)
print("SAMPLE ROWS")
print("=" * 60)
print(con.sql(f"SELECT * FROM read_csv_auto('{TRANS}') LIMIT 5"))

print("=" * 60)
print("CLASS BALANCE (transaction-level)")
print("=" * 60)
print(con.sql(f"""
    SELECT "Is Laundering" AS label, COUNT(*) AS n,
           ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 4) AS pct
    FROM read_csv_auto('{TRANS}')
    GROUP BY 1 ORDER BY 1
"""))

print("=" * 60)
print("TIMESTAMP RANGE")
print("=" * 60)
print(con.sql(f"""
    SELECT MIN(Timestamp) AS min_ts, MAX(Timestamp) AS max_ts
    FROM read_csv_auto('{TRANS}')
"""))

print("=" * 60)
print("CURRENCIES & PAYMENT FORMATS")
print("=" * 60)
print(con.sql(f"""
    SELECT "Receiving Currency" AS currency, COUNT(*) AS n
    FROM read_csv_auto('{TRANS}') GROUP BY 1 ORDER BY n DESC
"""))
print(con.sql(f"""
    SELECT "Payment Format" AS fmt, COUNT(*) AS n
    FROM read_csv_auto('{TRANS}') GROUP BY 1 ORDER BY n DESC
"""))

print("=" * 60)
print("PATTERNS FILE — first 30 lines")
print("=" * 60)
with open(PATTERNS) as f:
    for i, line in enumerate(f):
        if i >= 30:
            break
        print(line.rstrip())
