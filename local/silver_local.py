"""Phase 1: Silver layer — clean, canonicalize, normalize, enrich. DuckDB, local."""
import duckdb

TRANS = "data/raw/HI-Small_Trans.csv"
con = duckdb.connect()

# Static FX snapshot (approx Sep 2022), units: USD per 1 unit of currency.
con.sql("""
CREATE TABLE fx (currency VARCHAR, to_usd DOUBLE);
INSERT INTO fx VALUES
 ('US Dollar',1.0),('Euro',1.0),('UK Pound',1.15),('Swiss Franc',1.03),
 ('Yuan',0.14),('Shekel',0.29),('Rupee',0.0125),('Ruble',0.0165),
 ('Yen',0.0070),('Bitcoin',20000.0),('Canadian Dollar',0.76),
 ('Australian Dollar',0.68),('Mexican Peso',0.050),('Saudi Riyal',0.266),
 ('Brazil Real',0.19);
""")

raw_n = con.sql(f"SELECT COUNT(*) FROM read_csv_auto('{TRANS}')").fetchone()[0]
print(f"raw rows:            {raw_n:,}")

con.sql(f"""
CREATE TABLE silver AS
WITH dedup AS (
  SELECT DISTINCT * FROM read_csv_auto('{TRANS}')
)
SELECT
  ROW_NUMBER() OVER (ORDER BY Timestamp) AS tx_id,
  Timestamp                              AS ts,
  "From Bank"                            AS from_bank,
  "From Bank" || '_' || Account          AS from_account,
  "To Bank"                              AS to_bank,
  "To Bank" || '_' || Account_1          AS to_account,
  "Amount Paid"                          AS amount_paid,
  "Payment Currency"                     AS payment_currency,
  "Amount Received"                      AS amount_received,
  "Receiving Currency"                   AS receiving_currency,
  "Payment Format"                       AS payment_format,
  "Is Laundering"                        AS is_laundering,
  "Amount Paid" * fx.to_usd              AS amount_usd,
  (("From Bank" || '_' || Account) = ("To Bank" || '_' || Account_1)) AS is_self_loop,
  ("From Bank" != "To Bank")             AS is_cross_bank,
  ("Payment Currency" != "Receiving Currency") AS is_cross_currency,
  ("Amount Paid" > 0 AND "Amount Paid" = ROUND("Amount Paid", -2)) AS is_round_amount,
  ("Amount Paid" * fx.to_usd >= 8000 AND "Amount Paid" * fx.to_usd < 10000) AS is_sub_threshold
FROM dedup
JOIN fx ON fx.currency = dedup."Payment Currency"
""")

silver_n = con.sql("SELECT COUNT(*) FROM silver").fetchone()[0]
print(f"after dedup:         {silver_n:,}  (removed {raw_n - silver_n:,})")

print("\nflag counts:")
print(con.sql("""
SELECT
  SUM(is_self_loop::INT)     AS self_loops,
  SUM(is_cross_bank::INT)    AS cross_bank,
  SUM(is_cross_currency::INT) AS cross_currency,
  SUM(is_round_amount::INT)  AS round_amount,
  SUM(is_sub_threshold::INT) AS sub_threshold
FROM silver
"""))

# Account-level table: degrees, volumes, label (positive if in ANY laundering tx)
con.sql("""
CREATE TABLE accounts AS
WITH sends AS (
  SELECT from_account AS account_id, from_bank AS bank,
         COUNT(*) AS out_tx, SUM(amount_usd) AS out_usd,
         MAX(is_laundering) AS lbl
  FROM silver GROUP BY 1, 2
),
recvs AS (
  SELECT to_account AS account_id, to_bank AS bank,
         COUNT(*) AS in_tx, SUM(amount_usd) AS in_usd,
         MAX(is_laundering) AS lbl
  FROM silver GROUP BY 1, 2
)
SELECT
  COALESCE(s.account_id, r.account_id) AS account_id,
  COALESCE(s.bank, r.bank)             AS bank,
  COALESCE(out_tx, 0)                  AS out_tx,
  COALESCE(in_tx, 0)                   AS in_tx,
  COALESCE(out_usd, 0)                 AS out_usd,
  COALESCE(in_usd, 0)                  AS in_usd,
  GREATEST(COALESCE(s.lbl, 0), COALESCE(r.lbl, 0)) AS is_laundering_account
FROM sends s FULL OUTER JOIN recvs r ON s.account_id = r.account_id
""")

print("\naccount-level summary:")
print(con.sql("""
SELECT COUNT(*) AS accounts,
       SUM(is_laundering_account) AS positive_accounts,
       ROUND(100.0 * SUM(is_laundering_account) / COUNT(*), 4) AS positive_pct
FROM accounts
"""))

con.sql("COPY silver TO 'silver/transactions_clean.parquet' (FORMAT PARQUET, COMPRESSION SNAPPY)")
con.sql("COPY accounts TO 'silver/accounts.parquet' (FORMAT PARQUET, COMPRESSION SNAPPY)")
print("\nwrote silver/transactions_clean.parquet and silver/accounts.parquet")
