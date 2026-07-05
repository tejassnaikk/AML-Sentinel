"""Phase 3b: parse *_Patterns.txt ground truth, evaluate graph detection against it."""
import re
import duckdb
import pandas as pd

PATTERNS = "data/raw/HI-Small_Patterns.txt"
FEATURES = "features/account_graph_features.parquet"

# --- parse patterns file: state machine over BEGIN/END blocks ---
attempts = []   # (attempt_id, typology, src_acct, dst_acct)
typology = None
attempt_id = -1
with open(PATTERNS) as f:
    for line in f:
        line = line.strip()
        if line.startswith("BEGIN LAUNDERING ATTEMPT"):
            attempt_id += 1
            m = re.search(r"BEGIN LAUNDERING ATTEMPT - ([A-Z\- ]+?)(?::|$)", line)
            typology = m.group(1).strip() if m else "UNKNOWN"
        elif line.startswith("END LAUNDERING ATTEMPT"):
            typology = None
        elif typology and line:
            p = line.split(",")
            # cols: ts, from_bank, from_acct, to_bank, to_acct, ...
            src = f"{p[1]}_{p[2]}"
            dst = f"{p[3]}_{p[4]}"
            attempts.append((attempt_id, typology, src, dst))

truth = pd.DataFrame(attempts, columns=["attempt_id", "typology", "src", "dst"])
n_attempts = truth["attempt_id"].nunique()
print(f"parsed {n_attempts:,} laundering attempts, {len(truth):,} transactions")
print("\nattempts by typology:")
print(truth.groupby("typology")["attempt_id"].nunique().sort_values(ascending=False).to_string())

# ground-truth account set
truth_accounts = pd.unique(pd.concat([truth["src"], truth["dst"]]))
print(f"\nunique accounts in ground truth: {len(truth_accounts):,}")

# --- join against graph features ---
con = duckdb.connect()
feats = con.sql(f"SELECT * FROM '{FEATURES}'").df()
feats["is_truth"] = feats["account_id"].isin(set(truth_accounts))
covered = feats["is_truth"].sum()
print(f"ground-truth accounts present in graph: {covered:,} / {len(truth_accounts):,}")

# --- detection checks by typology-relevant signal ---
print("\n--- signal enrichment: truth accounts vs rest ---")
for col in ["in_cycle_component", "pagerank", "in_degree", "out_degree", "passthrough_ratio"]:
    t = feats.loc[feats.is_truth, col].astype(float)
    r = feats.loc[~feats.is_truth, col].astype(float)
    print(f"{col:>22}:  truth mean {t.mean():.6g}   rest mean {r.mean():.6g}   lift {t.mean()/max(r.mean(),1e-12):.1f}x")

# --- CYCLE typology: do truth cycle accounts sit in nontrivial SCCs? ---
cycle_accounts = pd.unique(pd.concat([
    truth.loc[truth.typology.str.contains("CYCLE"), "src"],
    truth.loc[truth.typology.str.contains("CYCLE"), "dst"],
]))
cyc = feats[feats.account_id.isin(set(cycle_accounts))]
if len(cyc):
    rate_truth = cyc["in_cycle_component"].mean()
    rate_all = feats["in_cycle_component"].mean()
    print(f"\nCYCLE accounts in nontrivial SCC: {rate_truth:.1%}  (graph-wide base rate {rate_all:.1%})")

# --- community concentration: are attempts contained in few communities? ---
acct2comm = dict(zip(feats.account_id, feats.community_id))
per_attempt = truth.assign(
    comm_src=truth.src.map(acct2comm), comm_dst=truth.dst.map(acct2comm)
)
def n_comms(g):
    vals = pd.concat([g.comm_src, g.comm_dst]).dropna()
    return vals.nunique()
comm_counts = per_attempt.groupby("attempt_id").apply(n_comms, include_groups=False)
print(f"\ncommunity concentration: median communities spanned per attempt = {comm_counts.median():.0f}")
print(f"attempts fully inside a single community: {(comm_counts == 1).mean():.1%}")
