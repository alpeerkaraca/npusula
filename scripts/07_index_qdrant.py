"""Builds a category-balanced Qdrant index from real title context vectors."""
from pathlib import Path
import pandas as pd

from backend.adapters.storage import QdrantPostStore
from backend.config import settings
from backend.services.canonical_taxonomy import CANONICAL_CATEGORIES, classify_post_category
from backend.services.context_engine import ContextEngine
from backend.services.tag_taxonomy import align_tags

PARQUET_FILE = Path("data/processed/posts.parquet")
CONTEXT_ENGINE_OUTPUT = Path("artifacts/qdrant_context_engine.joblib")


def _canonical_category(row: pd.Series) -> str:
    result = classify_post_category(
        str(row.get("title") or ""),
        row.get("category_l1"),
        row.get("category_l2"),
        row.get("concept"),
    )
    return str(result["primary_category"])


def index_qdrant(top_k: int = 10_000):
    print(f"Loading posts from {PARQUET_FILE}...")
    df = pd.read_parquet(PARQUET_FILE)
    print(f"Loaded {len(df):,} total posts.")

    # Context is title-only. Empty-title rows cannot receive a genuine text vector.
    df = df[df["title"].fillna("").astype(str).str.strip().str.len() >= 3].copy()
    df["category_l1"] = df.apply(_canonical_category, axis=1)
    # Retrieval tags keep only semantically aligned hashtags: the Qdrant payload
    # feeds the advisor's tag suggestions, so `unknown`/mismatched tags must not
    # survive into the index (plan §6.2).
    df["tags"] = df.apply(
        lambda row: align_tags(row.get("tags"), context_category=row["category_l1"])["aligned_semantic"],
        axis=1,
    )

    # Select each category's top quintile, then take an equal deterministic quota.
    per_category = max(1, top_k // len(CANONICAL_CATEGORIES))
    selected_groups = []
    for category in CANONICAL_CATEGORIES:
        group = df[df["category_l1"] == category]
        if group.empty:
            continue
        cutoff = group["popularity_score"].quantile(0.80)
        successful = group[group["popularity_score"] >= cutoff]
        selected = successful.sort_values(
            ["popularity_score", "published_at_utc"], ascending=[False, False]
        ).head(per_category)
        selected_groups.append(selected)
        print(f"  {category}: selected {len(selected):,} from top quintile")

    if not selected_groups:
        raise RuntimeError("No category-balanced posts were eligible for indexing.")
    combined = pd.concat(selected_groups, ignore_index=True).head(top_k)

    print("Fitting title-only context encoder...")
    engine = ContextEngine(svd_dim=settings.VECTOR_DIM)
    engine.fit(df["title"].fillna("").astype(str).tolist())
    CONTEXT_ENGINE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    engine.save(CONTEXT_ENGINE_OUTPUT)
    embeddings = engine.encode_titles(combined["title"].fillna("").astype(str).tolist())
    combined["text_embedding"] = [row for row in embeddings]
    posts = combined.to_dict(orient="records")
    print(f"Total posts to index into Qdrant: {len(posts):,}")

    store = QdrantPostStore()
    if not store.is_healthy():
        print("Warning: Qdrant is not responding. Ensure container is running.")
        return

    # Clear previous collection to wipe any old unfiltered points
    try:
        print(f"Resetting collection '{settings.QDRANT_COLLECTION}'...")
        store.client.delete_collection(settings.QDRANT_COLLECTION)
        store._ensure_collection()
    except Exception as e:
        print(f"Notice during collection reset: {e}")
        store._ensure_collection()

    # Upsert in batches of 250
    batch_size = 250
    total_indexed = 0
    for i in range(0, len(posts), batch_size):
        batch = posts[i : i + batch_size]
        indexed = store.upsert_posts(batch)
        total_indexed += indexed
        print(f"Indexed batch {i // batch_size + 1} ({total_indexed:,} / {len(posts):,} posts)...")

    print(f"Qdrant indexing complete! Total clean indexed in '{settings.QDRANT_COLLECTION}': {total_indexed:,}")


if __name__ == "__main__":
    index_qdrant()
