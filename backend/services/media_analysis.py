"""Uploaded-media (photo/video) analysis: validation, frame sampling, CLIP zero-shot.

Scope notes that shape this module:

- The SMPD corpus ships **no media files** (see `flickr_smpd_dataset.md`), so no
  image feature can be added to the 36-column popularity model and no retraining
  happens here. Instead, image analysis feeds the *inputs* the existing pipeline
  already consumes: a canonical category hint and hashtags.
- Below the calibrated confidence/margin floors we report "uncertain" (None)
  rather than letting argmax pick the first class — the silent-fallback failure
  documented in HIKAYE.md (section 9).
- Heavy imports (torch/transformers/Pillow/imageio-ffmpeg) are deliberately lazy:
  the API must start, and the text-only advisor path must work, without them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import io
import json
import logging
import math
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import uuid
from typing import Any, Literal

import httpx
import numpy as np

from backend.config import settings
from backend.prompts import build_vision_analysis_prompt
from backend.schemas.media import MediaAnalysis, MediaAnalysisResponse
from backend.services.canonical_taxonomy import CANONICAL_CATEGORIES

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
IMAGE_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
VIDEO_MIME_TYPES = {"video/mp4", "video/quicktime", "video/webm"}

# Pillow's decompression-bomb guard: reject absurd pixel counts early.
MAX_IMAGE_PIXELS = 50_000_000

# `classify_post_category` assigns exactly this confidence when no taxonomy
# keyword matched (`canonical_taxonomy.py`), i.e. "the text told us nothing".
# Kept as a named constant so the media override rule stays readable.
TEXT_CATEGORY_NO_MATCH_CONFIDENCE = 0.30

TopicSource = Literal["text", "media", "judge"]
MediaKind = Literal["photo", "video"]


# --------------------------------------------------------------------------
# Errors (mapped to HTTP status codes by the API layer)
# --------------------------------------------------------------------------
class MediaError(Exception):
    """Base class for media-pipeline failures; `status_code` maps to HTTP."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class MediaTooLargeError(MediaError):
    status_code = 413


class MediaTypeError(MediaError):
    status_code = 415


class MediaValidationError(MediaError):
    status_code = 422


class MediaUnavailableError(MediaError):
    """Raised when the vision stack (libraries or weights) is not available."""

    status_code = 503


# --------------------------------------------------------------------------
# Pure helpers: limits, sampling, merge rules (no model, no I/O)
# --------------------------------------------------------------------------
def detect_media_kind(filename: str, content_type: str) -> MediaKind:
    """Classifies an upload by extension and declared MIME type; rejects the rest."""
    suffix = Path(filename or "").suffix.lower()
    mime = (content_type or "").split(";")[0].strip().lower()

    if suffix in IMAGE_EXTENSIONS and (not mime or mime in IMAGE_MIME_TYPES):
        return "photo"
    if suffix in VIDEO_EXTENSIONS and (not mime or mime in VIDEO_MIME_TYPES):
        return "video"
    if mime in IMAGE_MIME_TYPES:
        return "photo"
    if mime in VIDEO_MIME_TYPES:
        return "video"
    raise MediaTypeError(
        "Desteklenmeyen dosya türü. Görsel için jpeg/png/webp, video için mp4/mov/webm yükleyin."
    )


def size_limit_bytes(kind: MediaKind) -> int:
    megabytes = settings.MAX_IMAGE_MB if kind == "photo" else settings.MAX_VIDEO_MB
    return int(megabytes * 1024 * 1024)


def check_size(kind: MediaKind, size_bytes: int) -> None:
    limit = size_limit_bytes(kind)
    if size_bytes <= 0:
        raise MediaValidationError("Boş dosya yüklenemez.")
    if size_bytes > limit:
        raise MediaTooLargeError(
            f"Dosya çok büyük: {size_bytes / (1024 * 1024):.1f} MB. "
            f"Üst sınır {limit / (1024 * 1024):.0f} MB."
        )


def read_upload_capped(stream: Any, limit_bytes: int, chunk_size: int = 1024 * 1024) -> bytes:
    """Reads an upload while enforcing the size cap.

    Content-Length is not trusted: the cap is applied to the bytes actually
    received, so a lying header cannot push an unbounded payload into memory.
    """
    buffer = bytearray()
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit_bytes:
            raise MediaTooLargeError(
                f"Dosya çok büyük. Üst sınır {limit_bytes / (1024 * 1024):.0f} MB."
            )
    return bytes(buffer)


def evenly_spaced_timestamps(duration_seconds: float, count: int) -> list[float]:
    """Timestamps at the centre of `count` equal buckets, in seconds.

    Centre sampling structurally avoids the near-black first/last frames that
    PLANNINGG.md §2.4 warns about, without needing a brightness heuristic.
    """
    if count <= 0:
        return []
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        return [0.0] * count
    step = duration_seconds / count
    return [round(step * (i + 0.5), 3) for i in range(count)]


def choose_topic_source(
    text_similarity: float,
    confident_threshold: float,
    media_topic_confident: bool,
) -> TopicSource:
    """Escalation ladder: confident text, else a confident image, else the LLM judge.

    The image sits *before* the judge on purpose: the judge is a network call
    with a deterministic fallback, while the image is evidence we already hold.
    """
    if text_similarity >= confident_threshold:
        return "text"
    if media_topic_confident:
        return "media"
    return "judge"


def should_use_media_category(media_category_confident: bool) -> bool:
    """Decides whether an analysed upload owns the category.

    The image wins whenever it is confident. It describes the file the user
    actually attached, whereas the text classifier is a keyword map built for
    SMPD's controlled metadata and mislabels free text (the "tech" prefix
    matches "techniques", turning a recipe into technology). The two scores are
    not comparable anyway: the text score is a match-density count, the image
    score a softmax probability.

    The caller still falls back to the text category when the image is
    uncertain, because `media_category_confident` is False for a null category.
    """
    return media_category_confident


def merge_tags(
    media_tags: list[str],
    retrieved_tags: list[str],
    fallback_tags: list[str],
    limit: int = 3,
) -> list[str]:
    """Media tags lead, then retrieval tags, then topic defaults; de-duplicated.

    Media tags describe the file the user actually attached, so they outrank
    tags inferred from a corpus whose titles are English and often unrelated.
    """
    merged: list[str] = []
    seen: set[str] = set()
    for source in (media_tags, retrieved_tags, fallback_tags):
        for tag in source:
            if not isinstance(tag, str):
                continue
            cleaned = tag.strip()
            if not cleaned:
                continue
            if not cleaned.startswith("#"):
                cleaned = f"#{cleaned}"
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
            if len(merged) >= limit:
                return merged
    return merged


def _require_pillow():
    try:
        from PIL import Image  # noqa: PLC0415 - lazy by design
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise MediaUnavailableError(
            "Görsel işleme kütüphanesi (Pillow) kurulu değil."
        ) from exc
    return Image


def _require_imageio_ffmpeg():
    try:
        import imageio_ffmpeg  # noqa: PLC0415 - lazy by design
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise MediaUnavailableError(
            "Video işleme kütüphanesi (imageio-ffmpeg) kurulu değil."
        ) from exc
    return imageio_ffmpeg


def validate_image_bytes(data: bytes) -> tuple[int, int, str]:
    """Verifies the payload decodes as an allow-listed image within the pixel budget."""
    Image = _require_pillow()
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()  # consumes the file object; the image must be reopened
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = (image.format or "").upper()
    except MediaUnavailableError:
        raise
    except Exception as exc:
        raise MediaValidationError("Yüklenen dosya geçerli bir görsel değil.") from exc

    if image_format not in {"JPEG", "PNG", "WEBP"}:
        raise MediaTypeError(f"Desteklenmeyen görsel formatı: {image_format or 'bilinmiyor'}.")
    if width <= 0 or height <= 0:
        raise MediaValidationError("Görsel boyutları okunamadı.")
    if width * height > MAX_IMAGE_PIXELS:
        raise MediaValidationError(
            f"Görsel çözünürlüğü çok yüksek: {width}x{height}."
        )
    return width, height, image_format


@dataclass
class VideoMeta:
    duration_seconds: float
    fps: float
    width: int
    height: int


def probe_video(path: Path) -> VideoMeta:
    """Reads container metadata through imageio-ffmpeg's bundled ffmpeg."""
    imageio_ffmpeg = _require_imageio_ffmpeg()
    generator = None
    try:
        generator = imageio_ffmpeg.read_frames(str(path))
        meta: dict[str, Any] = next(generator)
    except StopIteration as exc:
        raise MediaValidationError("Video okunamadı.") from exc
    except MediaUnavailableError:
        raise
    except Exception as exc:
        raise MediaValidationError("Video dosyası çözümlenemedi.") from exc
    finally:
        if generator is not None:
            generator.close()

    duration = float(meta.get("duration") or 0.0)
    size = meta.get("size") or (0, 0)
    return VideoMeta(
        duration_seconds=duration,
        fps=float(meta.get("fps") or 0.0),
        width=int(size[0]),
        height=int(size[1]),
    )


def check_video_limits(meta: VideoMeta) -> None:
    if meta.duration_seconds <= 0:
        raise MediaValidationError("Videonun süresi okunamadı.")
    if meta.duration_seconds > settings.MAX_VIDEO_SECONDS:
        raise MediaTooLargeError(
            f"Video çok uzun: {meta.duration_seconds:.1f} sn. "
            f"Üst sınır {settings.MAX_VIDEO_SECONDS:.0f} sn."
        )


def extract_frames(path: Path, timestamps: list[float]) -> list[Any]:
    """Decodes one frame per timestamp using fast seeks (deterministic, no full scan)."""
    Image = _require_pillow()
    imageio_ffmpeg = _require_imageio_ffmpeg()
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    frames: list[Any] = []
    for timestamp in timestamps:
        command = [
            ffmpeg_exe, "-v", "error",
            "-ss", f"{max(timestamp, 0.0):.3f}",
            "-i", str(path),
            "-frames:v", "1",
            "-f", "image2pipe", "-vcodec", "png", "-",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=30, check=False)
        except subprocess.TimeoutExpired:
            logger.warning("frame seek timed out at %.2fs", timestamp)
            continue
        if completed.returncode != 0 or not completed.stdout:
            logger.debug("frame at %.2fs could not be decoded", timestamp)
            continue
        try:
            frames.append(Image.open(io.BytesIO(completed.stdout)).convert("RGB"))
        except Exception:  # pragma: no cover - corrupt frame stream
            continue
    return frames


def create_video_storyboard(frames: list[Any]) -> Any:
    """Combines representative video frames into a 2x2 storyboard grid image.

    If only 1 frame is present, returns that frame directly.
    For 2+ frames, samples up to 4 evenly spaced frames and tiles them into a
    (448, 448) 2x2 grid so vision language models can perceive temporal progression.
    """
    Image = _require_pillow()
    if not frames:
        raise MediaValidationError("Medyadan hiç kare çözümlenemedi.")
    if len(frames) == 1:
        return frames[0]

    n = len(frames)
    if n >= 4:
        indices = [int(i * (n - 1) / 3) for i in range(4)]
        selected = [frames[idx] for idx in indices]
    else:
        selected = frames[:]
        while len(selected) < 4:
            selected.append(selected[-1])

    tile_size = (224, 224)
    canvas = Image.new("RGB", (tile_size[0] * 2, tile_size[1] * 2), color=(0, 0, 0))
    positions = [
        (0, 0),
        (tile_size[0], 0),
        (0, tile_size[1]),
        (tile_size[0], tile_size[1]),
    ]
    for frame, pos in zip(selected, positions):
        resized = frame.copy()
        resized.thumbnail(tile_size)
        offset_x = pos[0] + (tile_size[0] - resized.width) // 2
        offset_y = pos[1] + (tile_size[1] - resized.height) // 2
        canvas.paste(resized, (offset_x, offset_y))

    return canvas



# --------------------------------------------------------------------------
# Prompt banks (curated, English prompts -> Turkish labels)
# --------------------------------------------------------------------------
# Category prompts mirror `canonical_taxonomy.CANONICAL_CATEGORIES` exactly; a
# few templates per label are averaged, which is the standard zero-shot recipe.
CATEGORY_PROMPTS: dict[str, list[str]] = {
    "technology": ["a photo about technology and computers", "a photo of software or coding", "a photo of gadgets and devices"],
    "automotive": ["a photo of a car", "a photo of a vehicle on the road", "a photo of a motorcycle or truck"],
    "fashion_beauty": ["a photo about fashion and clothing", "a photo of makeup and cosmetics", "a photo of a personal style outfit"],
    "travel_tourism": ["a travel photo of a destination", "a photo of a holiday and sightseeing", "a photo of a hotel or a famous place"],
    "food_dining": ["a photo of food and meals", "a photo of coffee or drinks", "a photo of a restaurant table"],
    "entertainment_gaming": ["a photo of video games", "a photo about movies, tv or music", "a photo of a concert stage"],
    "sports_fitness": ["a photo about sports", "a photo of a gym workout", "a photo of running or a team game"],
    "nature_wildlife": ["a photo of nature and landscape", "a photo of an animal", "a photo of plants and flowers"],
    "art_design": ["a photo of an artwork", "a photo about design and architecture", "a photo of a painting or sculpture"],
    "business_economy": ["a photo about business and office work", "a photo of money and finance", "a photo of a meeting or a workplace"],
    "social_lifestyle": ["a photo of family and friends", "a photo of daily life at home", "a photo of a celebration or event"],
}

# The ten Turkish topics used across the advisor. Visually abstract topics
# (finance, entrepreneurship, education) are included so the ladder always has a
# candidate, but they are expected to land under the confidence floor and defer
# to the LLM judge — which is the intended behaviour, not a defect.
TOPIC_PROMPTS: dict[str, list[str]] = {
    "Yapay Zeka": ["a photo about artificial intelligence", "a photo of a computer running an ai model"],
    "Yazılım": ["a photo of a computer screen with code", "a photo of a software developer workspace"],
    "Teknoloji Trendleri": ["a photo of new technology gadgets", "a photo of consumer electronics"],
    "Oyun": ["a photo of video games and consoles", "a photo of a gaming setup"],
    "Eğitim": ["a photo of books and studying", "a photo of a classroom or lecture"],
    "Finans": ["a photo of money and investments", "a photo of financial charts and banking"],
    "Spor": ["a photo of sport and training", "a photo of a gym or a stadium"],
    "Kültür-Sanat": ["a photo of art and culture", "a photo of a museum, music or photography"],
    "Girişimcilik": ["a photo of a start-up office and teamwork", "a photo of a business meeting"],
    "Yaşam": ["a photo of daily life, coffee and family moments", "a photo of travel, nature or celebrations"],
}

# Only visually decidable concepts belong here: a photo cannot show
# "leadership" or "borsa", and suggesting such a tag would be a guess dressed up
# as evidence. Keys are the Turkish display tags used in `suggested_tags`.
IMAGE_TAG_PROMPTS: dict[str, list[str]] = {
    "#yapayzeka": ["artificial intelligence", "a computer running a machine learning model"],
    "#yazılım": ["software and programming", "a screen showing code"],
    "#kodlama": ["coding on a laptop", "programming source code"],
    "#teknoloji": ["modern technology devices", "electronics and gadgets"],
    "#oyun": ["video games", "a gaming console and controller"],
    "#espor": ["esports competition", "a gaming tournament setup"],
    "#spor": ["sports activity", "a sport game in action"],
    "#fitness": ["gym workout", "weight training and fitness"],
    "#koşu": ["running outdoors", "a person jogging"],
    "#bisiklet": ["a bicycle ride", "cycling outdoors"],
    "#futbol": ["a football match", "football players on a pitch"],
    "#basketbol": ["a basketball game", "basketball players"],
    "#kahve": ["a cup of coffee", "coffee shop latte art"],
    "#yemek": ["a plate of food", "a cooked meal"],
    "#tatlı": ["dessert and cake", "sweet pastries"],
    "#sağlık": ["healthy food and wellness", "a healthy lifestyle"],
    "#moda": ["fashion and clothing", "a stylish outfit"],
    "#makyaj": ["makeup and cosmetics", "a beauty routine"],
    "#seyahat": ["travel and sightseeing", "a journey to another city"],
    "#tatil": ["holiday vacation", "beach and relaxation"],
    "#plaj": ["a beach with sea", "sandy seaside"],
    "#kamp": ["camping outdoors", "a tent in nature"],
    "#doğa": ["nature landscape", "mountains, forest and sky"],
    "#günbatımı": ["sunset over the horizon", "golden hour sky"],
    "#hayvan": ["an animal", "a pet like a cat or a dog"],
    "#sanat": ["a work of art", "painting and artistic expression"],
    "#müzik": ["music performance", "a musician with an instrument"],
    "#konser": ["a live concert stage", "a crowd at a music festival"],
    "#sinema": ["cinema and film", "a movie theatre screen"],
    "#fotoğrafçılık": ["a camera and photography", "a photographer taking a picture"],
    "#mimari": ["architecture and buildings", "a modern building facade"],
    "#şehir": ["a city street", "an urban skyline"],
    "#kitap": ["books and reading", "a person reading a book"],
    "#aile": ["a family together", "parents and children"],
    "#çocuk": ["a child playing", "kids having fun"],
    "#araba": ["a car", "an automobile on the road"],
}

LABEL_BANKS: dict[str, dict[str, list[str]]] = {
    "category": CATEGORY_PROMPTS,
    "topic": TOPIC_PROMPTS,
    "tag": IMAGE_TAG_PROMPTS,
}

# CLIP's learned logit scale; standard for zero-shot classification.
CLIP_LOGIT_SCALE = 100.0


# --------------------------------------------------------------------------
# MediaAnalyzer: CLIP image embedding + zero-shot label scoring
# --------------------------------------------------------------------------
class MediaAnalyzer:
    """Multimodal vision analyzer supporting local multimodal LLM/VLM and zero-shot embeddings."""

    def __init__(
        self,
        model_name: str | None = None,
        cache_dir: Path | None = None,
        backend: str | None = None,
    ):
        if backend is not None:
            self.backend = backend.strip().lower()
        elif model_name and ("/" in model_name or "clip" in model_name.lower()):
            self.backend = "clip"
        else:
            self.backend = getattr(settings, "MEDIA_ANALYZER_BACKEND", "llm").strip().lower()

        if self.backend in ("llm", "vlm", "gemma"):
            self.model_name = model_name or settings.LLM_MODEL_NAME
        else:
            self.model_name = model_name or settings.VISION_MODEL_NAME
        self.cache_dir = Path(cache_dir or settings.MEDIA_CACHE_DIR)
        self.llm_api_url = getattr(settings, "LLM_API_URL", getattr(settings, "GEMMA_API_URL", "http://127.0.0.1:11434"))
        self.gemma_api_url = self.llm_api_url  # Backward-compatible alias
        self.timeout = getattr(settings, "LLM_VISION_TIMEOUT_SECONDS", getattr(settings, "GEMMA_VISION_TIMEOUT_SECONDS", 15.0))
        self._lock = threading.Lock()
        self._ready = False
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None
        self._device: Any = None
        self._banks: dict[str, tuple[list[str], Any]] = {}
        self._load_error: str | None = None

    @property
    def is_ready(self) -> bool:
        if self.backend in ("llm", "vlm", "gemma"):
            return self._ready
        return self._model is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def warm_up(self) -> bool:
        """Loads model or verifies LLM service connectivity; returns False instead of raising."""
        try:
            self._ensure_loaded()
            return True
        except MediaError as exc:
            logger.warning("media analyzer unavailable: %s", exc.message)
            return False
        except Exception as exc:
            logger.warning("media analyzer warm-up failed: %s", exc)
            return False

    # -- model lifecycle ---------------------------------------------------
    def _ensure_loaded(self) -> None:
        if self.is_ready:
            return
        with self._lock:
            if self.is_ready:
                return
            if self.backend in ("llm", "vlm", "gemma"):
                self._load_llm_vision()
            else:
                self._load_clip()

    def _load_llm_vision(self) -> None:
        """Verifies LLM endpoint is accessible and vision-capable model is available."""
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{self.llm_api_url.rstrip('/')}/api/tags")
                if resp.status_code != 200:
                    raise MediaUnavailableError(
                        f"LLM servisine erişilemedi (HTTP {resp.status_code})."
                    )
                models = [m.get("name") for m in resp.json().get("models", [])]
                target_base = self.model_name.split(":")[0]
                has_model = self.model_name in models or any(
                    m and m.startswith(target_base) for m in models
                )
                if not has_model:
                    raise MediaUnavailableError(
                        f"LLM servisi üzerinde '{self.model_name}' modeli bulunamadı."
                    )
            self._ready = True
            logger.info("media analyzer ready (vlm vision): %s at %s", self.model_name, self.llm_api_url)
        except Exception as exc:
            self._load_error = str(exc)
            raise MediaUnavailableError(
                f"Görsel analiz servisi hazır değil ({self.llm_api_url}): {exc}"
            ) from exc

    _load_gemma = _load_llm_vision  # Backward-compatible alias

    def _load_clip(self) -> None:
        try:
            import torch  # noqa: PLC0415 - lazy by design
            from transformers import CLIPModel, CLIPProcessor  # noqa: PLC0415
        except ImportError as exc:
            self._load_error = str(exc)
            raise MediaUnavailableError(
                "Görsel analizi için gerekli kütüphaneler kurulu değil (torch/transformers)."
            ) from exc

        candidates = self._device_candidates(torch)

        last_error: Exception | None = None
        for device in candidates:
            try:
                # use_safetensors is required, not cosmetic: transformers refuses
                # to load .bin checkpoints on torch < 2.6 (CVE-2025-32434), and
                # torch is pinned to 2.4.1 by the DirectML plugin. The safetensors
                # restriction does not apply, so this picks the safetensors
                # revision of the repo.
                model = CLIPModel.from_pretrained(
                    self.model_name, cache_dir=str(self.cache_dir), use_safetensors=True
                )
                processor = CLIPProcessor.from_pretrained(
                    self.model_name, cache_dir=str(self.cache_dir)
                )
                model.to(device)
                model.eval()
                self._torch = torch
                self._model = model
                self._processor = processor
                self._device = device
                self._banks = self._build_label_banks(torch)
                logger.info("media analyzer ready: %s on %s", self.model_name, device)
                return
            except Exception as exc:  # pragma: no cover - depends on device/weights
                last_error = exc
                logger.warning("CLIP load failed on %s: %s", device, exc)

        self._load_error = str(last_error)
        raise MediaUnavailableError(
            "Görsel analiz modeli yüklenemedi. Ağırlıkların indirildiğinden emin olun "
            "(scripts/download_clip_model.py)."
        )

    def _device_candidates(self, torch) -> list[Any]:
        """Device order for CLIP, driven by `MEDIA_DEVICE`.

        Defaults to CPU: DirectML rejects this model, and CPU inference is fast
        enough that paying the DirectML attempt at every start-up is not worth
        it. `MEDIA_DEVICE=auto` restores the GPU-first order.
        """
        preference = (settings.MEDIA_DEVICE or "cpu").strip().lower()
        if preference == "auto":
            from backend.services.device import device_manager  # noqa: PLC0415

            primary = device_manager.device
            return [primary] if str(primary) == "cpu" else [primary, torch.device("cpu")]
        if preference in {"cuda", "directml"}:
            try:
                from backend.services.device import device_manager  # noqa: PLC0415

                return [device_manager.device, torch.device("cpu")]
            except Exception:  # pragma: no cover - device manager optional
                logger.warning("MEDIA_DEVICE=%s requested but unavailable; using CPU", preference)
        return [torch.device("cpu")]

    def _build_label_banks(self, torch) -> dict[str, tuple[list[str], Any]]:
        banks: dict[str, tuple[list[str], Any]] = {}
        for group, bank in LABEL_BANKS.items():
            labels: list[str] = []
            vectors = []
            for label, prompts in bank.items():
                inputs = self._processor(
                    text=prompts, padding=True, truncation=True, return_tensors="pt"
                ).to(self._device)
                with torch.inference_mode():
                    features = self._model.get_text_features(**inputs)
                features = torch.nn.functional.normalize(features, dim=-1)
                vectors.append(features.mean(dim=0))
                labels.append(label)
            matrix = torch.nn.functional.normalize(torch.stack(vectors), dim=-1)
            banks[group] = (labels, matrix)
        return banks

    # -- inference ---------------------------------------------------------
    def _embed_images(self, images: list[Any]) -> np.ndarray:
        """L2-normalized embeddings for a batch of PIL images."""
        torch = self._torch
        inputs = self._processor(images=images, return_tensors="pt").to(self._device)
        with torch.inference_mode():
            features = self._model.get_image_features(**inputs)
        features = torch.nn.functional.normalize(features, dim=-1)
        return features.detach().cpu().numpy().astype(np.float32)

    def _video_embedding(self, frames: list[Any]) -> np.ndarray:
        """normalize(mean(normalize(frame_i))) — PLANNINGG.md §2.4's video contract."""
        frame_vectors = self._embed_images(frames)
        mean_vector = frame_vectors.mean(axis=0)
        norm = float(np.linalg.norm(mean_vector))
        if norm == 0.0:
            raise MediaValidationError("Videodan anlamlı bir görsel vektör çıkarılamadı.")
        return (mean_vector / norm).astype(np.float32)

    def _group_scores(self, embedding: np.ndarray, group: str) -> tuple[list[str], np.ndarray]:
        labels, matrix = self._banks[group]
        matrix_np = matrix.detach().cpu().numpy().astype(np.float32)
        logits = CLIP_LOGIT_SCALE * (matrix_np @ embedding)
        logits = logits - logits.max()
        probabilities = np.exp(logits)
        probabilities /= probabilities.sum()
        return labels, probabilities

    def _top_label(self, labels: list[str], probabilities: np.ndarray) -> tuple[str | None, float, float]:
        """Top-1 label with its probability and the margin over the runner-up.

        Returns (None, p1, margin) when the floors are not met, so callers can
        report uncertainty instead of guessing.
        """
        order = np.argsort(probabilities)[::-1]
        best = float(probabilities[order[0]])
        runner_up = float(probabilities[order[1]]) if len(order) > 1 else 0.0
        margin = best - runner_up
        if best < settings.MEDIA_MIN_PROB or margin < settings.MEDIA_MIN_MARGIN:
            return None, best, margin
        return labels[order[0]], best, margin

    def _tag_labels(self, labels: list[str], probabilities: np.ndarray) -> list[str]:
        """Tags for a confident image, or none at all.

        The tag bank is small, so a flat distribution publishes confidently
        wrong labels: a car photo scored "#seyahat" 0.33 and "#hayvan" 0.21
        while "#araba" sat at 0.02. Raising the per-tag floor does not fix that
        -- it only hides some of the wrong labels while dropping correct weak
        ones (a city photo's "#mimari" at 0.09). Gating the whole set on the top
        label's own confidence, using the same floor the category uses, reports
        "no tags" for that photo instead of three unrelated ones.
        """
        order = np.argsort(probabilities)[::-1]
        if len(order) == 0 or float(probabilities[order[0]]) < settings.MEDIA_MIN_PROB:
            return []
        selected = [
            labels[index]
            for index in order
            if float(probabilities[index]) >= settings.MEDIA_TAG_MIN_PROB
        ]
        return selected[: settings.MEDIA_TOP_TAGS]

    def _analyze_with_llm_vision(
        self,
        image: Any,
        is_video: bool = False,
    ) -> tuple[str | None, float, float, str | None, float, list[str]]:
        """Invokes multimodal vision LLM with base64 image and parses structured JSON output."""
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        prompt = build_vision_analysis_prompt(
            categories=CANONICAL_CATEGORIES,
            topics=list(TOPIC_PROMPTS.keys()),
            is_video=is_video,
        )

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": 256},
        }

        endpoint = f"{self.llm_api_url.rstrip('/')}/api/generate"
        attempts = max(1, getattr(settings, "LLM_RETRY_COUNT", getattr(settings, "GEMMA_RETRY_COUNT", 2)))
        parsed_data: dict[str, Any] | None = None
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(endpoint, json=payload)
                    if resp.status_code == 200:
                        res_json = resp.json()
                        raw_response = (
                            res_json.get("response", "").strip()
                            or res_json.get("thinking", "").strip()
                        )
                        if raw_response:
                            clean_json = raw_response
                            if "</think>" in clean_json:
                                clean_json = clean_json.split("</think>")[-1].strip()
                            clean_json = re.sub(r"^<think>.*?</think>", "", clean_json, flags=re.DOTALL).strip()
                            if "```" in clean_json:
                                clean_json = re.sub(r"```json\s*", "", clean_json)
                                clean_json = re.sub(r"```\s*", "", clean_json)
                            try:
                                parsed_data = json.loads(clean_json)
                                break
                            except Exception as json_err:
                                logger.warning("VLM JSON parse failed on attempt %d: %s", attempt + 1, json_err)
                    logger.warning(
                        "vlm vision attempt %d failed: status=%s", attempt + 1, resp.status_code
                    )
            except Exception as exc:
                last_exc = exc
                logger.warning("vlm vision attempt %d error: %s", attempt + 1, exc)
            import time
            time.sleep(0.25)

        if parsed_data is None:
            raise MediaUnavailableError(
                f"Görsel analizi tamamlayamadı ({self.model_name}): {last_exc or 'Boş yanıt'}"
            )

        raw_cat = parsed_data.get("category")
        category = raw_cat if raw_cat in CANONICAL_CATEGORIES else None

        try:
            cat_conf = float(parsed_data.get("category_confidence", 0.85))
        except (TypeError, ValueError):
            cat_conf = 0.85

        raw_top = parsed_data.get("topic")
        topic = raw_top if raw_top in TOPIC_PROMPTS else None

        try:
            top_conf = float(parsed_data.get("topic_confidence", 0.80))
        except (TypeError, ValueError):
            top_conf = 0.80

        raw_tags = parsed_data.get("tags") or []
        tags: list[str] = []
        for t in raw_tags:
            if isinstance(t, str):
                cleaned = t.strip()
                if not cleaned:
                    continue
                if not cleaned.startswith("#"):
                    cleaned = f"#{cleaned}"
                if len(cleaned) > 1 and cleaned.lower() not in [x.lower() for x in tags]:
                    tags.append(cleaned)
        suggested_tags = tags[: settings.MEDIA_TOP_TAGS]

        if cat_conf < settings.MEDIA_MIN_PROB:
            category = None
            suggested_tags = []

        margin = max(0.0, cat_conf - settings.MEDIA_MIN_PROB)
        return category, cat_conf, margin, topic, top_conf, suggested_tags

    _analyze_with_gemma = _analyze_with_llm_vision  # Backward-compatible alias

    # -- public API --------------------------------------------------------
    def analyze(
        self,
        *,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> MediaAnalysis:
        """Validates and analyses one uploaded file end to end."""
        kind = detect_media_kind(filename, content_type)
        check_size(kind, len(data))
        self._ensure_loaded()

        if kind == "photo":
            width, height, _ = validate_image_bytes(data)
            Image = _require_pillow()
            with Image.open(io.BytesIO(data)) as image:
                frame = image.convert("RGB")
            frames = [frame]
            duration: float | None = None
        else:
            frames, duration, width, height = self._decode_video(data)

        if not frames:
            raise MediaValidationError("Medyadan hiç kare çözümlenemedi.")

        if self.backend in ("llm", "vlm", "gemma"):
            storyboard = create_video_storyboard(frames) if kind == "video" else frames[0]
            category, category_conf, category_margin, topic, topic_conf, tags = self._analyze_with_llm_vision(
                storyboard, is_video=(kind == "video")
            )
            embedding_dim = 2560
        else:
            embedding = (
                self._video_embedding(frames) if len(frames) > 1 else self._embed_images(frames)[0]
            )

            category_labels, category_probs = self._group_scores(embedding, "category")
            topic_labels, topic_probs = self._group_scores(embedding, "topic")
            tag_labels, tag_probs = self._group_scores(embedding, "tag")

            category, category_conf, category_margin = self._top_label(category_labels, category_probs)
            topic, topic_conf, _ = self._top_label(topic_labels, topic_probs)
            tags = self._tag_labels(tag_labels, tag_probs) if category is not None else []
            embedding_dim = int(embedding.shape[0])

        return MediaAnalysis(
            media_kind=kind,
            filename=filename,
            content_type=content_type,
            size_bytes=len(data),
            frames_analyzed=len(frames),
            duration_seconds=duration,
            width=int(width),
            height=int(height),
            topic=topic,
            topic_confidence=round(float(topic_conf), 4),
            canonical_category=category,
            category_confidence=round(float(category_conf), 4),
            category_margin=round(float(category_margin), 4),
            suggested_tags=tags,
            uncertain=category is None,
            model_name=self.model_name,
            embedding_dim=embedding_dim,
        )

    def _decode_video(self, data: bytes) -> tuple[list[Any], float, int, int]:
        """Writes the upload to a temp file (ffmpeg needs a path) and samples frames."""
        with tempfile.TemporaryDirectory(prefix="npusula-media-") as tmpdir:
            path = Path(tmpdir) / "upload.bin"
            path.write_bytes(data)
            meta = probe_video(path)
            check_video_limits(meta)
            timestamps = evenly_spaced_timestamps(meta.duration_seconds, settings.VIDEO_FRAME_COUNT)
            frames = extract_frames(path, timestamps)
        return frames, meta.duration_seconds, meta.width, meta.height


# --------------------------------------------------------------------------
# TTL store for analyses referenced by `media_id`
# --------------------------------------------------------------------------
class MediaAnalysisStore:
    """In-memory, TTL-bounded store mirroring the profile-decision pattern.

    Analyses are demo-lifetime artefacts: a restart losing them is acceptable,
    and it keeps uploaded media out of any persistent store.
    """

    def __init__(self, ttl_seconds: int | None = None, max_entries: int = 128):
        self.ttl_seconds = ttl_seconds or settings.MEDIA_ANALYSIS_TTL_SECONDS
        self.max_entries = max_entries
        self._entries: dict[str, tuple[float, MediaAnalysisResponse]] = {}
        self._lock = threading.Lock()

    def put(self, analysis: MediaAnalysis) -> MediaAnalysisResponse:
        now = datetime.now(timezone.utc)
        record = MediaAnalysisResponse(
            **analysis.model_dump(),
            media_id=uuid.uuid4().hex,
            created_at_utc=now,
        )
        with self._lock:
            self._purge_locked(now.timestamp())
            while len(self._entries) >= self.max_entries:
                oldest = min(self._entries, key=lambda key: self._entries[key][0])
                self._entries.pop(oldest, None)
            self._entries[record.media_id] = (now.timestamp(), record)
        return record

    def get(self, media_id: str) -> MediaAnalysisResponse | None:
        with self._lock:
            self._purge_locked(datetime.now(timezone.utc).timestamp())
            entry = self._entries.get(media_id)
        return entry[1] if entry else None

    def _purge_locked(self, now: float) -> None:
        expired = [key for key, (created, _) in self._entries.items() if now - created > self.ttl_seconds]
        for key in expired:
            self._entries.pop(key, None)
