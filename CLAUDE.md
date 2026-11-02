# twinsim（建物・工場の人流のデジタルツインのシミュレータ）

`main` はシミュレータだけ。設定は JSON、Python のライブラリとして呼べる（docs/library.md）。MOPF との連携と人物照合はブランチ `with-mopf` にある。
作業場所: `~/twinsim-lib` が `main`、`~/twinsim` が `with-mopf`（`saferamp-omni/links` などが `~/twinsim` の配置を読むので、`~/twinsim` は動かさない）。

人流解析（`~/MOPF_ALL_video`）とデジタルツインの構想のためのシミュレータ。医療のプロジェクト（`~/digitaltwin`）とは別のリポジトリ。
Isaac Sim の環境（`isim`）と人物の部品は `~/digitaltwin` のもの（`twinsim/isaac/vendor/` に写してある。直すときは元と合わせる）。

## 守ること

- GPU（RTX PRO 6000 ×4）は他の利用者と共有。使う前に `nvidia-smi` で空きを確かめる。検出などと同じマシンで動かすときは同じ GPU 1 枚に載せるのが既定（`one-gpu` が選ぶ）で、分けるときも 2 枚まで。描画など長い計算は、所要時間と GPU を示して確認を取ってから始める。
- データ（計算の結果・動画）は git に入れない。置き場所は `~/dt-data/twinsim/`（runs/）。
  - 実在の建物の映像・図面（秘密保持の対象）から作ったもの（空間・映像）は、このリポジトリにも共有の場所にも置かない。
  - 特定の企業や建物の名前は、`main` の文書とコードに書かない（提案の資料としても見せるため）。名前の入った版はブランチ `with-partner-names`。
- 素材の利用条件（twinsim/spaces/*/space.yaml の license）を確かめてから、作ったデータを外に出す。
- GitHub は非公開の `fujisawa-yoshihiko/twinsim`（2026-10-23 作成）。送るのは確認を取ってから。構成と開発の手順は docs/architecture.md。
- 文書は日本語と英語の 2 つ（README.md・README.en.md、docs/*.md・docs/*.en.md）。片方を直したら、もう片方も同じように直す。
- 出力の形を変えたら docs/formats.md（と英語版）と README の「出力の形」を直す（ほかの人が学習データとして読む）。
