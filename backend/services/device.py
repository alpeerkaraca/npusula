"""Hardware device management for GPU acceleration on Windows (DirectML / AMD Radeon)."""
import logging
from typing import Any
import torch

try:
    import torch_directml

    DIRECTML_AVAILABLE = torch_directml.is_available()
except ImportError:
    DIRECTML_AVAILABLE = False

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manages compute device selection for PyTorch models."""

    def __init__(self):
        self.device_type = "cpu"
        self.device_name = "CPU"
        self.device = torch.device("cpu")

        if DIRECTML_AVAILABLE:
            try:
                self.device = torch_directml.device(0)  # Primary GPU: RX 9070 XT
                self.device_type = "directml"
                raw_name = torch_directml.device_name(0)
                self.device_name = raw_name.replace("\x00", "").strip()
            except Exception as e:
                logger.warning("failed to initialize DirectML device: %s; using CPU", e)
        elif torch.cuda.is_available():
            self.device = torch.device("cuda:0")
            self.device_type = "cuda"
            self.device_name = torch.cuda.get_device_name(0).replace("\x00", "").strip()

    def get_device(self) -> Any:
        return self.device

    def get_info(self) -> dict[str, Any]:
        return {
            "gpu_available": self.device_type != "cpu",
            "device_type": self.device_type,
            "device_name": self.device_name,
            "pytorch_version": torch.__version__,
        }


device_manager = DeviceManager()
