"""Retrieval service managing vector search and hashtag aggregation."""
from collections import Counter
from pathlib import Path

from backend.adapters.storage import InMemoryPostStore, QdrantPostStore, SimilarPostStore
from backend.config import settings
from backend.schemas.recommendation import SimilarPost
from backend.services.context_engine import ContextEngine
from backend.services.tag_taxonomy import NSFW_TAGS

# Seed topic index mapping for topic-aligned embedding projection
TOPIC_ORDER = [
    "Yapay Zeka",
    "Yazılım",
    "Teknoloji Trendleri",
    "Oyun",
    "Eğitim",
    "Finans",
    "Spor",
    "Kültür-Sanat",
    "Girişimcilik",
    "Yaşam",
]


# Backwards-compatible export for callers. Only hard safety terms are blocked;
# ambiguous brands, colours, dates, and places are evaluated in their context.
BLOCKED_TAG_KEYWORDS = NSFW_TAGS

TOPIC_DEFAULT_TAGS: dict[str, list[str]] = {
    "Yapay Zeka": ["#yapayzeka", "#ai", "#derinogrenme", "#makineogrenmesi", "#kodlama"],
    "Yazılım": ["#yazılım", "#python", "#kodlama", "#developer", "#backend"],
    "Teknoloji Trendleri": ["#teknoloji", "#techtrends", "#inovasyon", "#gelecek", "#donanım"],
    "Oyun": ["#oyun", "#gaming", "#gamer", "#espor", "#oyunhaberleri"],
    "Eğitim": ["#eğitim", "#öğrenme", "#kişiselgelişim", "#kitap", "#bilgi"],
    "Finans": ["#finans", "#ekonomi", "#yatırım", "#borsa", "#kripto"],
    "Spor": ["#spor", "#fitness", "#antrenman", "#sağlık", "#motivasyon"],
    "Kültür-Sanat": ["#sanat", "#kültür", "#tasarım", "#fotoğrafçılık", "#sinema"],
    "Girişimcilik": ["#girişimcilik", "#startup", "#işdünyası", "#liderlik", "#motivasyon"],
    "Yaşam": ["#yaşam", "#lifestyle", "#güzellik", "#moda", "#bakım", "#sağlık"],
}


def is_clean_tag(tag: str) -> bool:
    """Applies format and hard-safety checks without a blind semantic blacklist."""
    t = tag.lower().lstrip("#").strip()
    if len(t) < 3:
        return False
    return t not in NSFW_TAGS and not t.isnumeric()


class RetrievalService:
    """Retrieves top-performing similar posts and aggregates high-impact hashtags."""

    def __init__(self, store: SimilarPostStore | None = None, context_engine_path: Path | None = None):
        self.context_engine = ContextEngine(svd_dim=settings.VECTOR_DIM)
        engine_path = context_engine_path or (settings.ARTIFACTS_DIR / "qdrant_context_engine.joblib")
        if engine_path.exists():
            self.context_engine.load(engine_path)
        else:
            self._fit_fallback_context_engine()

        if store is not None:
            self.store = store
        else:
            # Try connecting to Qdrant first, fallback to InMemory
            try:
                qdrant_store = QdrantPostStore()
                if qdrant_store.is_healthy():
                    self.store = qdrant_store
                else:
                    self.store = InMemoryPostStore()
            except Exception:
                self.store = InMemoryPostStore()

        if isinstance(self.store, InMemoryPostStore) and not self.store.vectors:
            self._seed_fallback_store()

    def _fit_fallback_context_engine(self) -> None:
        """Fits a deterministic local encoder for offline/dev operation."""
        corpus = [
            "Yapay zeka makine öğrenmesi derin öğrenme model optimizasyonu",
            "Yazılım geliştirme Python backend kodlama",
            "Teknoloji donanım mobil cihaz inovasyon",
            "Video oyunları espor oyun motoru",
            "Eğitim öğrenme kitap bilgi",
            "Finans ekonomi yatırım borsa kripto",
            "Spor fitness antrenman koşu",
            "Kültür sanat tasarım sinema müzik",
            "Girişimcilik startup iş liderlik",
            "Yaşam moda güzellik bakım aile",
            "Seyahat turizm doğa macera otel",
        ]
        self.context_engine.fit(corpus)

    def _seed_fallback_store(self) -> None:
        """Provides real text-encoded exemplars when Qdrant is unavailable."""
        posts = []
        for idx, topic in enumerate(TOPIC_ORDER):
            tags = TOPIC_DEFAULT_TAGS.get(topic, ["#ensosyal"])
            title = f"{topic} için başarılı içerik stratejileri"
            posts.append({
                "post_id": f"fallback-{idx + 1}",
                "title": title,
                "tags": tags,
                "category_l1": None,
                "hour": [9, 12, 18, 21][idx % 4],
                "weekday": idx % 7,
                "popularity_score": 7.0 + idx / 10.0,
                "media_type": "photo",
                "text_embedding": self.generate_text_vector(title),
            })
        self.store.upsert_posts(posts)

    def generate_text_vector(self, topic: str, dim: int = 512) -> list[float]:
        """Encodes query text with the same fitted context engine as the index."""
        if dim != self.context_engine.svd_dim:
            raise ValueError(
                f"Requested vector dimension {dim} does not match encoder dimension "
                f"{self.context_engine.svd_dim}."
            )
        result = self.context_engine.transform(topic)
        return [float(result[f"context_dim_{i}"]) for i in range(dim)]

    def search_similar_posts(
        self,
        topic: str,
        limit: int = 5,
        category_filter: str | None = None,
    ) -> list[SimilarPost]:
        query_vec = self.generate_text_vector(topic, dim=settings.VECTOR_DIM)
        return self.store.search(query_vec, limit=limit, category=category_filter)

    def extract_top_tags(
        self,
        similar_posts: list[SimilarPost],
        top_k: int = 3,
        topic: str | None = None,
    ) -> list[str]:
        """Calculates tag impact weighted by post frequency * popularity_score with safety filtering."""
        tag_scores: Counter[str] = Counter()

        for post in similar_posts:
            weight = post.popularity_score
            for tag in post.tags:
                clean_tag = tag.strip()
                if not clean_tag.startswith("#"):
                    clean_tag = f"#{clean_tag}"
                if clean_tag and is_clean_tag(clean_tag) and clean_tag.lower() not in ["#ensosyal"]:
                    tag_scores[clean_tag] += weight

        top_pairs = tag_scores.most_common(top_k)
        extracted = [tag for tag, _ in top_pairs]

        # If filtered tags are fewer than top_k, supplement with high-relevance topic defaults
        defaults = TOPIC_DEFAULT_TAGS.get(topic or "", ["#Teknoloji", "#Gelişim", "#EnSosyal"])
        for d in defaults:
            if len(extracted) >= top_k:
                break
            if d not in extracted:
                extracted.append(d)

        return extracted[:top_k]
