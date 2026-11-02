"""twinsim: 建物の人流のシミュレータ（人の動き・状態の正解・カメラの枠の正解ラベル）。

    import twinsim
    result = twinsim.simulate("config.json", out_dir="runs/test")
    labels = result.mot("CamGate")

使える名前: simulate・open_result・Result・load_config・validate・template・list_templates・list_spaces・render。説明は docs/library.md。
"""

__version__ = "0.5.0"
__all__ = ["Result", "list_spaces", "list_templates", "load_config", "open_result", "render", "run", "simulate", "template", "validate"]

_WHERE = {"Result": "api", "run": "api", "simulate": "api", "template": "api", "render": "api", "open_result": "api",
          "load_config": "scenario", "list_templates": "scenario", "list_spaces": "space"}


def validate(config_src, overrides=None):
    """設定を確かめ、既定の値を足した設定（dict）を返す。誤りがあれば ValueError。計算はしない。"""
    from .scenario import load_scenario
    return load_scenario(config_src, overrides)


def __getattr__(name):  # import twinsim を軽くするため、使うときに読み込む
    if name in _WHERE:
        from importlib import import_module
        return getattr(import_module(f".{_WHERE[name]}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
