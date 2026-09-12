"""Deprecated compatibility entry point for the unified residual trainer."""
from pathlib import Path
import runpy


def train_gpu_model(*_args, **_kwargs) -> None:
    """Runs the canonical B0-M5 LightGBM trainer.

    GPU-specific tabular training was retired because it used the banned follower
    proxy and an obsolete feature contract. The function name remains so existing
    local commands fail forward into the supported residual pipeline.
    """
    trainer = Path(__file__).with_name("05_train_lgbm.py")
    namespace = runpy.run_path(str(trainer))
    namespace["train"]()


if __name__ == "__main__":
    train_gpu_model()
