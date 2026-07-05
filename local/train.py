"""Phase 4b: XGBoost account-level risk model. AUPRC primary. MLflow tracked."""
import duckdb
import numpy as np
import mlflow
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import average_precision_score, precision_score, recall_score

FEATURES = "features/model_features.parquet"
SEED = 42

df = duckdb.connect().sql(f"SELECT * FROM '{FEATURES}'").df()
y = df["label"].values
X = df.drop(columns=["account_id", "label"]).astype(float)
feat_names = list(X.columns)

X_tr, X_te, y_tr, y_te, id_tr, id_te = train_test_split(
    X, y, df["account_id"], test_size=0.2, stratify=y, random_state=SEED
)
spw = (y_tr == 0).sum() / (y_tr == 1).sum()
print(f"train {len(y_tr):,} ({y_tr.sum():,} pos) | test {len(y_te):,} ({y_te.sum():,} pos) | scale_pos_weight {spw:.1f}")

mlflow.set_experiment("aml-sentinel")
with mlflow.start_run(run_name="xgb_v1"):
    params = dict(
        n_estimators=400, max_depth=6, learning_rate=0.1,
        subsample=0.8, colsample_bytree=0.8,
        scale_pos_weight=spw, eval_metric="aucpr",
        tree_method="hist", random_state=SEED, n_jobs=-1,
    )
    mlflow.log_params(params)
    model = xgb.XGBClassifier(**params)
    model.fit(X_tr, y_tr, eval_set=[(X_te, y_te)], verbose=False)

    p = model.predict_proba(X_te)[:, 1]
    auprc = average_precision_score(y_te, p)
    base = y_te.mean()
    print(f"\nAUPRC: {auprc:.4f}  (random baseline = positive rate = {base:.4f}, lift {auprc/base:.1f}x)")
    mlflow.log_metric("auprc", auprc)
    mlflow.log_metric("auprc_baseline", base)

    order = np.argsort(-p)
    for k in [100, 500, 1000]:
        pk = y_te[order[:k]].mean()
        rk = y_te[order[:k]].sum() / y_te.sum()
        print(f"precision@{k}: {pk:.3f}   recall@{k}: {rk:.3f}")
        mlflow.log_metric(f"precision_at_{k}", pk)
        mlflow.log_metric(f"recall_at_{k}", rk)

    print("\ntop 10 features by gain:")
    imp = sorted(zip(feat_names, model.feature_importances_), key=lambda t: -t[1])
    for name, v in imp[:10]:
        print(f"  {name:>22}: {v:.4f}")
    mlflow.log_dict({n: float(v) for n, v in imp}, "feature_importance.json")

    model.get_booster().save_model("features/xgb_v1.json")
    mlflow.log_artifact("features/xgb_v1.json")
    print("\nmodel saved: features/xgb_v1.json (also logged to MLflow)")
