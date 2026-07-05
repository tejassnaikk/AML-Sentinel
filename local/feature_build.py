"""Phase 4a: assemble account-level model features = graph features + tx aggregates."""
import duckdb

SILVER = "silver/transactions_clean.parquet"
GRAPH = "features/account_graph_features.parquet"
OUT = "features/model_features.parquet"

con = duckdb.connect()

con.sql(f"""
CREATE TABLE tx_agg AS
WITH sends AS (
  SELECT from_account AS account_id,
         COUNT(*) AS n_out,
         SUM(amount_usd) AS usd_out,
         AVG(is_sub_threshold::INT) AS sub_thr_rate_out,
         AVG(is_cross_bank::INT) AS cross_bank_rate,
         AVG(is_cross_currency::INT) AS cross_ccy_rate,
         COUNT(DISTINCT payment_format) AS n_formats_out,
         COUNT(*) / GREATEST(DATE_DIFF('hour', MIN(ts), MAX(ts)), 1) AS out_per_hr,
         MAX(is_laundering) AS lbl_s
  FROM '{SILVER}' WHERE NOT is_self_loop GROUP BY 1
),
recvs AS (
  SELECT to_account AS account_id,
         COUNT(*) AS n_in,
         SUM(amount_usd) AS usd_in,
         AVG(is_sub_threshold::INT) AS sub_thr_rate_in,
         COUNT(*) / GREATEST(DATE_DIFF('hour', MIN(ts), MAX(ts)), 1) AS in_per_hr,
         MAX(is_laundering) AS lbl_r
  FROM '{SILVER}' WHERE NOT is_self_loop GROUP BY 1
),
selfl AS (
  SELECT from_account AS account_id,
         COUNT(*) AS n_self, SUM(amount_usd) AS usd_self,
         MAX(is_laundering) AS lbl_x
  FROM '{SILVER}' WHERE is_self_loop GROUP BY 1
)
SELECT
  COALESCE(s.account_id, r.account_id, x.account_id) AS account_id,
  COALESCE(n_out,0) AS n_out, COALESCE(n_in,0) AS n_in,
  COALESCE(usd_out,0) AS usd_out, COALESCE(usd_in,0) AS usd_in,
  COALESCE(n_self,0) AS n_self, COALESCE(usd_self,0) AS usd_self,
  COALESCE(sub_thr_rate_out,0) AS sub_thr_rate_out,
  COALESCE(sub_thr_rate_in,0) AS sub_thr_rate_in,
  COALESCE(cross_bank_rate,0) AS cross_bank_rate,
  COALESCE(cross_ccy_rate,0) AS cross_ccy_rate,
  COALESCE(n_formats_out,0) AS n_formats_out,
  COALESCE(out_per_hr,0) AS out_per_hr, COALESCE(in_per_hr,0) AS in_per_hr,
  -- symmetric balance: 0 = perfect pass-through (out ~= in), 1 = one-sided
  ABS(COALESCE(usd_out,0) - COALESCE(usd_in,0))
    / GREATEST(COALESCE(usd_out,0) + COALESCE(usd_in,0), 1.0) AS flow_imbalance,
  GREATEST(COALESCE(lbl_s,0), COALESCE(lbl_r,0), COALESCE(lbl_x,0)) AS label
FROM sends s
FULL OUTER JOIN recvs r ON s.account_id = r.account_id
FULL OUTER JOIN selfl x ON COALESCE(s.account_id, r.account_id) = x.account_id
""")

con.sql(f"""
CREATE TABLE features AS
SELECT
  t.*,
  COALESCE(g.in_degree, 0) AS in_degree,
  COALESCE(g.out_degree, 0) AS out_degree,
  COALESCE(g.pagerank, 0) AS pagerank,
  COALESCE(g.scc_size, 1) AS scc_size,
  COALESCE(g.in_cycle_component, FALSE) AS in_cycle_component,
  COALESCE(g.community_size, 1) AS community_size,
  (g.account_id IS NULL) AS graph_isolated
FROM tx_agg t
LEFT JOIN '{GRAPH}' g USING (account_id)
""")

print(con.sql("""
SELECT COUNT(*) AS accounts, SUM(label) AS positives,
       ROUND(100.0*SUM(label)/COUNT(*),4) AS pos_pct,
       SUM(graph_isolated::INT) AS selfloop_only
FROM features
"""))

con.sql(f"COPY features TO '{OUT}' (FORMAT PARQUET, COMPRESSION SNAPPY)")
print(f"wrote {OUT}")
print(con.sql(f"DESCRIBE SELECT * FROM '{OUT}'"))
