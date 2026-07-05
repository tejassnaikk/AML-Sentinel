"""Phase 5: score all accounts, assemble Gold tables incl. SAR candidates with explanations."""
import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb

FEATURES = "features/model_features.parquet"
MODEL = "features/xgb_v1.json"
TOP_K = 1000  # alert queue size (workload-driven, from precision@k curve)

con = duckdb.connect()
df = con.sql(f"SELECT * FROM '{FEATURES}'").df()
X = df.drop(columns=["account_id", "label"]).astype(float)

booster = xgb.Booster()
booster.load_model(MODEL)
df["risk_score"] = booster.predict(xgb.DMatrix(X, feature_names=list(X.columns)))
print(f"scored {len(df):,} accounts")

# ---- Gold 1: account_risk_features ----
con.sql("CREATE TABLE account_risk AS SELECT * FROM df")
con.sql("COPY account_risk TO 'gold/account_risk_features.parquet' (FORMAT PARQUET, COMPRESSION SNAPPY)")

# ---- Gold 2: suspicious_networks (nontrivial SCCs, aggregated) ----
graph = con.sql("SELECT * FROM 'features/account_graph_features.parquet'").df()
g = graph.merge(df[["account_id", "risk_score", "label"]], on="account_id", how="left")
nets = (
    g[(g.scc_size > 1) & (g.scc_size <= 50)]
    .groupby("scc_id")
    .agg(account_count=("account_id", "size"),
         total_flow_usd=("out_usd", "sum"),
         mean_risk=("risk_score", "mean"),
         max_risk=("risk_score", "max"),
         labeled_accounts=("label", "sum"))
    .reset_index()
    .rename(columns={"scc_id": "network_id"})
    .sort_values("max_risk", ascending=False)
)
nets["typology"] = "CYCLE-BEARING"  # SCC>1 by construction contains cycles
con.sql("CREATE TABLE nets AS SELECT * FROM nets")
con.sql("COPY nets TO 'gold/suspicious_networks.parquet' (FORMAT PARQUET, COMPRESSION SNAPPY)")
print(f"suspicious_networks: {len(nets):,} cycle-bearing networks")

# ---- Gold 3: sar_candidates (top-K with explanations + evidence) ----
top = df.nlargest(TOP_K, "risk_score").copy()

def explain(r):
    reasons = []
    if 1 < r.scc_size <= 50: reasons.append(f"member of a {int(r.scc_size)}-account cycle-bearing network")
    elif r.scc_size > 50: reasons.append("embedded in the graph core (dense strongly-connected region)")
    if r.sub_thr_rate_out > 0.2: reasons.append(f"{r.sub_thr_rate_out:.0%} of outgoing payments just under reporting threshold")
    if r.out_degree >= 10: reasons.append(f"fan-out to {int(r.out_degree)} counterparties")
    if r.in_degree >= 10: reasons.append(f"fan-in from {int(r.in_degree)} counterparties")
    if r.flow_imbalance < 0.1 and (r.usd_in + r.usd_out) > 0: reasons.append("near-perfect pass-through (outflow ~= inflow)")
    if r.out_per_hr > 5: reasons.append(f"high outbound velocity ({r.out_per_hr:.1f} tx/hr)")
    if r.cross_ccy_rate > 0.3: reasons.append("frequent cross-currency movement")
    return "; ".join(reasons) if reasons else "elevated composite risk across multiple weak signals"

top["explanation"] = top.apply(explain, axis=1)
top["status"] = "new"
top["candidate_id"] = ["SAR-%05d" % i for i in range(1, len(top) + 1)]

# evidence transactions: up to 5 tx ids per candidate
silver = con.sql("""
    SELECT tx_id, from_account, to_account FROM 'silver/transactions_clean.parquet'
""").df()
acct_set = set(top.account_id)
ev = silver[silver.from_account.isin(acct_set) | silver.to_account.isin(acct_set)].copy()
ev["account_id"] = np.where(ev.from_account.isin(acct_set), ev.from_account, ev.to_account)
ev_ids = ev.groupby("account_id")["tx_id"].apply(lambda s: ",".join(map(str, s.head(5))))
top["supporting_tx_ids"] = top.account_id.map(ev_ids).fillna("")

sar = top[["candidate_id", "account_id", "risk_score", "explanation", "supporting_tx_ids", "status", "label"]]
con.sql("CREATE TABLE sar AS SELECT * FROM sar")
con.sql("COPY sar TO 'gold/sar_candidates.parquet' (FORMAT PARQUET, COMPRESSION SNAPPY)")
tp = int(sar.label.sum())
print(f"sar_candidates: {len(sar):,} alerts; {tp} are labeled positives ({tp/len(sar):.1%} queue precision)")

# ---- Gold 4: model_performance ----
perf = pd.DataFrame([{
    "run_date": pd.Timestamp.today().date().isoformat(),
    "model": "xgb_v1", "auprc": 0.2492, "auprc_baseline": 0.0123,
    "precision_at_100": 0.950, "precision_at_500": 0.446, "precision_at_1000": 0.293,
    "alert_volume": TOP_K,
}])
con.sql("CREATE TABLE perf AS SELECT * FROM perf")
con.sql("COPY perf TO 'gold/model_performance.parquet' (FORMAT PARQUET, COMPRESSION SNAPPY)")

print("\ntop 5 SAR candidates:")
print(sar.head(5)[["candidate_id", "account_id", "risk_score", "explanation"]].to_string(index=False))
print("\nwrote 4 Gold tables to gold/")
