#!/usr/bin/env bash
# twinsim のコマンドの入口（pyproject.toml の依存を uv で用意して twinsim を実行する）。
#   ./run.sh serve            GUI（127.0.0.1:8770）     ./run.sh serve --url   開く URL を表示
#   ./run.sh templates        テンプレートの一覧         ./run.sh run <テンプレートか JSON のファイル>   計算（CPU）
#   ./run.sh render <結果の場所> [--frames a b]   描画（GPU。先に ./isaac_up.sh）
#   コマンドの一覧: ./run.sh --help
export TWINSIM_DATA=${TWINSIM_DATA:-$HOME/dt-data/twinsim}   # 結果の置き場所（git の外）
exec uv run --project "$(dirname "$(readlink -f "$0")")" --quiet twinsim "$@"
