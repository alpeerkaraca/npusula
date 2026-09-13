"""Vector storage adapters for post retrieval."""
import logging
from typing import Any, Protocol
import uuid
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from backend.config import settings
from backend.schemas.recommendation import SimilarPost

logger = logging.getLogger(__name__)


class SimilarPostStore(Protocol):
    """Protocol contract for similar post vector retrieval."""

    def upsert_posts(self, posts: list[dict[str, Any]]) -> int:
        """Upsert posts into vector index."""
        ...

    def search(
        self,
        query_vector: list[float],
        limit: int = 5,
        category: str | None = None,
    ) -> list[SimilarPost]:
        """Search similar posts by vector, optionally filtered by category."""
        ...

    def is_healthy(self) -> bool:
        """Check connection health."""
        ...


class QdrantPostStore:
    """Production vector store adapter using Qdrant running in Podman/Docker."""

    def __init__(self, host: str | None = None, port: int | None = None, collection: str | None = None):
        self.host = host or settings.QDRANT_HOST
        self.port = port or settings.QDRANT_PORT
        self.collection_name = collection or settings.QDRANT_COLLECTION
        self.client = QdrantClient(host=self.host, port=self.port, timeout=3.0)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)
            if not exists:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=settings.VECTOR_DIM,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
        except Exception as e:
            logger.warning("failed to ensure qdrant collection '%s': %s", self.collection_name, e)

    def is_healthy(self) -> bool:
        try:
            return self.client.get_collections() is not None
        except Exception:
            return False

    def upsert_posts(self, posts: list[dict[str, Any]]) -> int:
        points: list[qmodels.PointStruct] = []
        for idx, p in enumerate(posts):
            vec_val = p.get("text_embedding")
            if vec_val is None or (hasattr(vec_val, "__len__") and len(vec_val) == 0):
                vec_val = p.get("image_embedding")
            if vec_val is None:
                continue
            if isinstance(vec_val, np.ndarray):
                vector = vec_val.tolist()
            else:
                vector = list(vec_val)

            payload = {
                "post_id": str(p.get("post_id")),
                "title": str(p.get("title", "")),
                "tags": list(p.get("tags", [])),
                "category_l1": p.get("category_l1"),
                "hour": int(p.get("hour", 12)),
                "weekday": int(p.get("weekday", 0)),
                "popularity_score": float(p.get("popularity_score", 0.0)),
                "media_type": str(p.get("media_type", "photo")),
            }

            pid_str = str(p.get("post_id"))
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, pid_str))

            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)
        return len(points)

    def search(
        self,
        query_vector: list[float],
        limit: int = 5,
        category: str | None = None,
    ) -> list[SimilarPost]:
        query_filter = None
        if category:
            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="category_l1",
                        match=qmodels.MatchValue(value=category),
                    )
                ]
            )

        try:
            hits = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            ).points
        except Exception:
            hits = []

        if not hits and query_filter is not None:
            try:
                hits = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    limit=limit,
                    with_payload=True,
                ).points
            except Exception:
                hits = []

        results: list[SimilarPost] = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(
                SimilarPost(
                    post_id=str(payload.get("post_id", "")),
                    title=str(payload.get("title", "")),
                    hour=int(payload.get("hour", 12)),
                    weekday=int(payload.get("weekday", 0)),
                    popularity_score=round(float(payload.get("popularity_score", 0.0)), 2),
                    similarity=round(float(hit.score), 4),
                    tags=list(payload.get("tags", [])),
                )
            )
        return results


class InMemoryPostStore:
    """In-memory fallback vector store using numpy cosine similarity."""

    def __init__(self):
        self.vectors: list[np.ndarray] = []
        self.payloads: list[dict[str, Any]] = []

    def is_healthy(self) -> bool:
        return True

    def upsert_posts(self, posts: list[dict[str, Any]]) -> int:
        count = 0
        for p in posts:
            vec_val = p.get("text_embedding")
            if vec_val is None or (hasattr(vec_val, "__len__") and len(vec_val) == 0):
                vec_val = p.get("image_embedding")
            if vec_val is None:
                continue
            arr = np.array(vec_val, dtype=np.float32)
            if len(arr) != settings.VECTOR_DIM:
                continue
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm

            self.vectors.append(arr)
            self.payloads.append({
                "post_id": str(p.get("post_id")),
                "title": str(p.get("title", "")),
                "tags": list(p.get("tags", [])),
                "category_l1": p.get("category_l1"),
                "hour": int(p.get("hour", 12)),
                "weekday": int(p.get("weekday", 0)),
                "popularity_score": float(p.get("popularity_score", 0.0)),
                "media_type": str(p.get("media_type", "photo")),
            })
            count += 1
        return count

    def search(
        self,
        query_vector: list[float],
        limit: int = 5,
        category: str | None = None,
    ) -> list[SimilarPost]:
        if not self.vectors:
            return []

        q_vec = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec = q_vec / q_norm

        scores: list[tuple[int, float]] = []
        for idx, v in enumerate(self.vectors):
            if category and self.payloads[idx].get("category_l1") != category:
                continue
            sim = float(np.dot(q_vec, v))
            scores.append((idx, sim))

        # Fallback to no category filter if empty
        if not scores and category:
            for idx, v in enumerate(self.vectors):
                sim = float(np.dot(q_vec, v))
                scores.append((idx, sim))

        scores.sort(key=lambda item: item[1], reverse=True)
        top = scores[:limit]

        return [
            SimilarPost(
                post_id=str(self.payloads[idx]["post_id"]),
                title=str(self.payloads[idx]["title"]),
                hour=int(self.payloads[idx]["hour"]),
                weekday=int(self.payloads[idx]["weekday"]),
                popularity_score=round(float(self.payloads[idx]["popularity_score"]), 2),
                similarity=round(sim, 4),
                tags=list(self.payloads[idx]["tags"]),
            )
            for idx, sim in top
        ]
