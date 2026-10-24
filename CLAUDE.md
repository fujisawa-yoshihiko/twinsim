# twinsim（建物・工場の人流のデジタルツインのシミュレータ）

人流解析（`~/MOPF_ALL_video`、竹芝の研究）とデジタルツインの構想のためのシミュレータ。医療のプロジェクト（`~/digitaltwin`）とは別のリポジトリ。
Isaac Sim の環境（`isim`）と人物の部品は `~/digitaltwin` のもの（`isaac/vendor/` に写してある。直すときは元と合わせる）。

## 守ること

- GPU（RTX PRO 6000 ×4）は他の利用者と共有。使う前に `nvidia-smi` で空きを確かめ、同時に 2 枚まで。描画など長い計算は、所要時間と GPU を示して確認を取ってから始める。
- データ（計算の結果・動画）は git に入れない。置き場所は `~/dt-data/twinsim/`（runs/）。
  例外は報告のページ（`docs/report/<日付>/media/`）に載せる短い切り出し・画像だけ（1 回 30 MB まで、`tools/report_media.sh`・`tools/capture_gui.py` で作る）。
- 竹芝の実際の映像・図面（NDA の対象）から作ったもの（空間・映像）は、このリポジトリにも共有の場所にも置かない。
- 素材の利用条件（spaces/*/space.yaml の license）を確かめてから、作ったデータを外に出す。
- GitHub は非公開の `fujisawa-yoshihiko/twinsim`（2026-10-23 作成）。送るのは確認を取ってから。構成と開発の手順は docs/architecture.md。
- 文書は日本語と英語の 2 つ（README.md・README.en.md、docs/*.md・docs/*.en.md）。片方を直したら、もう片方も同じように直す。
- 出力の形を変えたら docs/formats.md（と英語版）と README の「出力の形」を直す（ほかの人が学習データとして読む）。
