#!/usr/bin/env bash
# 版を出す前の確かめ（CPU だけ、10 分ほど）。手順は docs/architecture.md の「版の出し方」。
#   tools/release_check.sh [作業の場所]
# 1. 書き方（ruff）と動作確認（pytest）
# 2. wheel を作り、きれいな環境（Python 3.10・3.13）に入れて動かす。同じ設定と種で、Python の版をまたいで正解が同じか
# 3. 秘密の情報（detect-secrets、作業ツリー）と、依存パッケージの既知の脆弱性（pip-audit、uv.lock の固定した版）
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${1:-$(mktemp -d)}
mkdir -p "$OUT"
step() { echo "== $(date +%H:%M:%S) $*"; }

step "書き方・動作確認"
uv run --group dev ruff check
uv run --group dev pytest -q

step "wheel をきれいな環境に入れて動かす"
rm -rf "$OUT/dist"
uv build --wheel --out-dir "$OUT/dist" -q
for py in 3.10 3.13; do
  rm -rf "$OUT/venv$py" "$OUT/run_py$py"
  uv venv -q --python "$py" "$OUT/venv$py"
  uv pip install -q --python "$OUT/venv$py/bin/python" "$OUT"/dist/*.whl
  (cd "$OUT" && "$OUT/venv$py/bin/twinsim" --version && "$OUT/venv$py/bin/twinsim" run office_gate_ev --out "$OUT/run_py$py" > "$OUT/run_py$py.log")
done
a=$(sha256sum "$OUT/run_py3.10/ground_truth.json" | cut -d' ' -f1)
b=$(sha256sum "$OUT/run_py3.13/ground_truth.json" | cut -d' ' -f1)
[ "$a" = "$b" ] || { echo "Python 3.10 と 3.13 で正解が違う"; exit 1; }
echo "Python 3.10・3.13 で正解が同じ（${a:0:16}）"

step "秘密の情報"
uvx --quiet detect-secrets scan --all-files --exclude-files '(\.venv/|\.pytest_cache/|\.ruff_cache/|uv\.lock$|\.npz$|\.jpg$|\.png$)' > "$OUT/secrets.json"
python3 - "$OUT/secrets.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))["results"]
for f, items in r.items():
    for it in items:
        print(f"{f}:{it['line_number']} {it['type']}")
sys.exit(1 if r else 0)
EOF
echo "見つからなかった"

step "依存パッケージの脆弱性"
uv export --locked --no-hashes --no-dev --no-emit-project > "$OUT/requirements.txt"
uvx --quiet pip-audit -r "$OUT/requirements.txt"

step "すべて通った（$OUT）"
