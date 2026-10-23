"""人物照合（ReID）のモデルで、人の切り出しから見た目の特徴（L2 で正規化したベクトル）を出す。CPU で動かす（uv run --group reid）。

モデル（重みは手元のファイル。ネットからは落とさない）:
  osnet_x0_25_msmt17  OSNet x0.25、MSMT17 で学習（MOPF の追跡 BoostTrack と同じ重み、~/MOPF_ALL_video/MOPF_CV_Native/models/reid/）
  osnet_x1_0_msmt17   OSNet x1.0、MSMT17 で学習（TWINSIM_DATA/models/reid/ に置く。torchreid の配布）
  clipreid_vitb16_msmt17  CLIP-ReID の ViT-B/16、MSMT17 で学習（TWINSIM_DATA/models/reid/clipreid_vitb16_msmt17.pth。CLIP-ReID の配布、論文で mAP 73.4）
ネットワークの定義は twinsim/vendor/（osnet.py は torchreid、clipreid.py は CLIP-ReID。どちらも MIT）。前処理は元の評価の設定と同じ（256×128）。
重みは中にコードを含まない形でだけ読む（torch.load(weights_only=True)）。
共用のマシンなので、CPU は既定で 8 本まで（TWINSIM_TORCH_THREADS）。
"""

import os
import time

import numpy as np

from . import config

IMAGENET = (np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32))
HALF = (np.array([0.5, 0.5, 0.5], np.float32), np.array([0.5, 0.5, 0.5], np.float32))
MODELS = {
    "osnet_x0_25_msmt17": {"arch": "osnet_x0_25", "num_classes": 1041, "norm": IMAGENET,
                           "weights": config.MOPF_CV / "models/reid/osnet_x0_25_msmt17.pt"},
    "osnet_x1_0_msmt17": {"arch": "osnet_x1_0", "num_classes": 1041, "norm": IMAGENET, "weights": config.DATA / "models/reid/osnet_x1_0_msmt17.pt"},
    "clipreid_vitb16_msmt17": {"arch": "clipreid", "norm": HALF, "weights": config.DATA / "models/reid/clipreid_vitb16_msmt17.pth"},
}


class Embedder:
    def __init__(self, name="osnet_x0_25_msmt17", threads=None, batch=64):
        import torch

        from .vendor import clipreid, osnet
        if name not in MODELS:
            raise ValueError(f"人物照合のモデル {name} はない（{', '.join(MODELS)}）")
        m = MODELS[name]
        if not m["weights"].exists():
            raise FileNotFoundError(f"重みがない: {m['weights']}")
        torch.set_num_threads(int(threads or os.environ.get("TWINSIM_TORCH_THREADS", 8)))
        self.torch, self.name, self.batch = torch, name, batch
        sd = torch.load(m["weights"], map_location="cpu", weights_only=True)
        sd = sd.get("state_dict", sd)
        sd = {k.removeprefix("module."): v for k, v in sd.items()}
        if m["arch"] == "clipreid":
            self.model = clipreid.ClipReIDImage()
            sd = {k: v.float() for k, v in sd.items() if k.startswith(("image_encoder.", "bottleneck.", "bottleneck_proj."))}
        else:
            self.model = getattr(osnet, m["arch"])(num_classes=m["num_classes"], loss="softmax")
        self.model.load_state_dict(sd)
        self.mean, self.std = m["norm"]
        self.model.eval()
        self.seconds, self.n = 0.0, 0

    def __call__(self, crops_bgr):
        """BGR の切り出しの列 → (n, d) の特徴（L2 で正規化）"""
        import cv2
        if not crops_bgr:
            return np.zeros((0, 1), np.float32)
        x = np.stack([cv2.resize(c, (128, 256))[..., ::-1].astype(np.float32) / 255.0 for c in crops_bgr])
        x = ((x - self.mean) / self.std).transpose(0, 3, 1, 2)
        out = []
        t0 = time.perf_counter()
        with self.torch.no_grad():
            for i in range(0, len(x), self.batch):
                out.append(self.model(self.torch.from_numpy(np.ascontiguousarray(x[i:i + self.batch]))).numpy())
        self.seconds += time.perf_counter() - t0
        self.n += len(x)
        f = np.concatenate(out)
        return f / np.maximum(np.linalg.norm(f, axis=1, keepdims=True), 1e-12)

    @property
    def ms_per_crop(self):
        return round(1000 * self.seconds / max(self.n, 1), 2)
