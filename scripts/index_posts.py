"""Indexes top-quartile successful posts into Qdrant."""
from backend.adapters.repository import PostRepository
from backend.adapters.storage import QdrantPostStore
from backend.config import settings


def index_posts():
    repo = PostRepository()
    posts = repo.get_successful_posts(percentile=75.0)
    print(f"Found {len(posts)} top-quartile posts to index.")

    store = QdrantPostStore()
    count = store.upsert_posts(posts)
    print(f"Successfully indexed {count} posts into Qdrant collection '{settings.QDRANT_COLLECTION}'.")


if __name__ == "__main__":
    index_posts()
