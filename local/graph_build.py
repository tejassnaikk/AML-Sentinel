"""Phase 3a: build directed account graph, run WCC/SCC/PageRank/community detection,
emit per-account graph features."""
import time
import duckdb
import igraph as ig

SILVER = "silver/transactions_clean.parquet"
OUT = "features/account_graph_features.parquet"
t0 = time.time()

con = duckdb.connect()

# Aggregate to account-pair edges, excluding self-loops
edges = con.sql(f"""
    SELECT from_account AS src, to_account AS dst,
           COUNT(*) AS tx_count, SUM(amount_usd) AS total_usd,
           MAX(is_laundering) AS any_laundering
    FROM '{SILVER}'
    WHERE NOT is_self_loop
    GROUP BY 1, 2
""").df()
print(f"edges (account pairs, self-loops excluded): {len(edges):,}  [{time.time()-t0:.1f}s]")

g = ig.Graph.TupleList(
    edges[["src", "dst"]].itertuples(index=False),
    directed=True,
)
g.es["tx_count"] = edges["tx_count"].tolist()
g.es["total_usd"] = edges["total_usd"].tolist()
print(f"graph: {g.vcount():,} nodes, {g.ecount():,} edges  [{time.time()-t0:.1f}s]")

names = g.vs["name"]

# Connected components
wcc = g.connected_components(mode="weak")
scc = g.connected_components(mode="strong")
wcc_sizes = [len(c) for c in wcc]
scc_membership = scc.membership
scc_sizes = {}
for m in scc_membership:
    scc_sizes[m] = scc_sizes.get(m, 0) + 1
print(f"WCC: {len(wcc):,} components, largest {max(wcc_sizes):,}")
n_cyclic = sum(1 for s in scc_sizes.values() if s > 1)
print(f"SCC: {n_cyclic:,} nontrivial (size>1) strong components -> cycle-bearing  [{time.time()-t0:.1f}s]")

# PageRank (edge-weighted by tx_count)
pagerank = g.pagerank(weights="tx_count")
print(f"PageRank done  [{time.time()-t0:.1f}s]")

# Community detection: label propagation on undirected copy (LPA is undirected in igraph)
gu = g.as_undirected(combine_edges={"tx_count": "sum"})
lpa = gu.community_label_propagation(weights="tx_count")
print(f"LPA: {len(lpa):,} communities, largest {max(len(c) for c in lpa):,}  [{time.time()-t0:.1f}s]")

# Per-node features
in_deg = g.degree(mode="in")
out_deg = g.degree(mode="out")
in_strength = g.strength(mode="in", weights="total_usd")
out_strength = g.strength(mode="out", weights="total_usd")

feat = duckdb.connect()
import pandas as pd
df = pd.DataFrame({
    "account_id": names,
    "in_degree": in_deg,
    "out_degree": out_deg,
    "in_usd": in_strength,
    "out_usd": out_strength,
    "pagerank": pagerank,
    "wcc_id": wcc.membership,
    "scc_id": scc_membership,
    "scc_size": [scc_sizes[m] for m in scc_membership],
    "in_cycle_component": [scc_sizes[m] > 1 for m in scc_membership],
    "community_id": lpa.membership,
})
df["community_size"] = df.groupby("community_id")["account_id"].transform("count")
# pass-through ratio: money out vs money in (mule signal), guarded
df["passthrough_ratio"] = (df["out_usd"] / (df["in_usd"] + 1.0)).clip(upper=100.0)

feat.sql("CREATE TABLE f AS SELECT * FROM df")
feat.sql(f"COPY f TO '{OUT}' (FORMAT PARQUET, COMPRESSION SNAPPY)")
print(f"wrote {OUT}: {len(df):,} rows, {len(df.columns)} features  [{time.time()-t0:.1f}s]")

print("\ntop 5 by pagerank:")
print(df.nlargest(5, "pagerank")[["account_id", "in_degree", "out_degree", "pagerank", "scc_size"]].to_string(index=False))
