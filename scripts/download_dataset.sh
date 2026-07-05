#!/bin/bash
set -euo pipefail
DATASET="ealtman2019/ibm-transactions-for-anti-money-laundering-aml"
DEST="data/raw"
mkdir -p "$DEST"

for f in "HI-Small_Trans.csv" "HI-Small_Patterns.txt"; do
  echo ">> downloading $f"
  kaggle datasets download -d "$DATASET" -f "$f" -p "$DEST"
done

for z in "$DEST"/*.zip; do
  [ -e "$z" ] && unzip -o "$z" -d "$DEST" && rm "$z"
done

echo ">> contents of $DEST:"
ls -lh "$DEST"
