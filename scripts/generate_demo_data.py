"""Script to generate realistic benchmark demo accounts and historical posts."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import numpy as np
import pandas as pd

from backend.schemas.post import MediaTypeEnum, PostRecord
from backend.services.history_feature import compute_leakage_free_history

# Seed for reproducibility
random.seed(42)
np.random.seed(42)

DATA_DIR = Path("data/processed")
DATA_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR = Path("artifacts")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

TOPICS = [
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

DEMO_ACCOUNTS = {
    "demo_user_01": {
        "user_id": "demo_user_01",
        "username": "zeynep_tech",
        "name": "Zeynep Kaya",
        "bio": "Yapay zeka ve büyük dil modelleri üzerine paylaşımlar yapan araştırmacı.",
        "declared_topics": ["Yapay Zeka", "Yazılım"],
        "post_count": 30,
        "type": "aligned",
    },
    "demo_user_02": {
        "user_id": "demo_user_02",
        "username": "murat_trends",
        "name": "Murat Demir",
        "bio": "Teknoloji dünyasındaki en yeni tüketici trendleri ve ürün lansmanları.",
        "declared_topics": ["Yapay Zeka"],
        "post_count": 25,
        "type": "drift",
    },
    "demo_user_03": {
        "user_id": "demo_user_03",
        "username": "ece_starter",
        "name": "Ece Yılmaz",
        "bio": "EnSosyal'e yeni katıldım. Sanat ve tasarım içerikleri keşfetmeyi seviyorum.",
        "declared_topics": ["Kültür-Sanat"],
        "post_count": 0,
        "type": "cold_start",
    },
}

TOPIC_KEYWORDS = {
    "Yapay Zeka": ["yapay zeka", "machine learning", "deep learning", "llm", "ai", "model", "gpt", "vision"],
    "Yazılım": ["yazılım", "python", "javascript", "backend", "frontend", "kodlama", "developer", "git"],
    "Teknoloji Trendleri": ["trend", "teknoloji trendleri", "lansman", "akıllı cihaz", "gadget", "apple", "yenilik", "dijital"],
    "Oyun": ["gaming", "espor", "oyun", "playstation", "steam", "gamer", "rpg", "twitch"],
    "Eğitim": ["eğitim", "öğrenme", "kurs", "üniversite", "akademik", "öğrenci", "kitap", "ders"],
    "Finans": ["finans", "borsa", "yatırım", "kripto", "ekonomi", "bütçe", "para", "portföy"],
    "Spor": ["spor", "futbol", "basketbol", "fitness", "antrenman", "koşu", "sağlık", "maraton"],
    "Kültür-Sanat": ["sanat", "müze", "sergi", "tiyatro", "sinema", "fotoğraf", "tasarım", "edebiyat"],
    "Girişimcilik": ["girişimcilik", "startup", "yatırım", "founder", "networking", "iş fikri", "büyüme"],
    "Yaşam": ["yaşam", "lifestyle", "seyahat", "gezi", "kahve", "doğa", "günlük", "minimalizm"],
}


def generate_embedding(seed_topic_idx: int, dim: int = 512) -> list[float]:
    """Generates a normalized 512-D synthetic embedding with slight topic cluster affinity."""
    vec = np.random.normal(0, 1, dim)
    # Give a small topic-specific bias to dimensions [topic_idx*20 : (topic_idx+1)*20]
    start = (seed_topic_idx * 20) % dim
    vec[start : start + 20] += 2.5
    norm = np.linalg.norm(vec)
    return (vec / norm).round(5).tolist()


def generate_posts() -> list[dict]:
    posts: list[dict] = []
    now = datetime.now(timezone.utc)

    # 1. User 01 posts (aligned: Yapay Zeka & Yazılım)
    for i in range(30):
        days_ago = 60 - i * 1.8
        pub_date = now - timedelta(days=days_ago, hours=random.randint(0, 12))
        topic = "Yapay Zeka" if i % 2 == 0 else "Yazılım"
        kw = random.sample(TOPIC_KEYWORDS[topic], 3)
        title = f"{topic} alanında yeni gelişmeler: {kw[0].capitalize()} ve {kw[1]}"
        tags = [f"#{t.replace(' ', '')}" for t in kw] + [f"#{topic.replace(' ', '')}"]
        score = round(random.gauss(6.3, 0.4), 2)

        posts.append({
            "schema_version": "1.0",
            "source": "demo_aligned",
            "post_id": f"p_u1_{i:03d}",
            "user_id": "demo_user_01",
            "published_at_utc": pub_date.isoformat(),
            "timezone": "UTC",
            "timezone_inferred": True,
            "title": title,
            "description": f"EnSosyal topluluğu için {topic} rehberi.",
            "tags": tags,
            "media_type": MediaTypeEnum.PHOTO.value,
            "media_available": True,
            "category_l1": topic,
            "category_l2": kw[0],
            "concept": kw[1],
            "latitude": None,
            "longitude": None,
            "user_followers": 1520,
            "user_following": 340,
            "popularity_score": score,
            "image_embedding": generate_embedding(TOPICS.index(topic)),
            "text_embedding": generate_embedding(TOPICS.index(topic)),
            "ingested_at_utc": now.isoformat(),
        })

    # 2. User 02 posts (drift: first 5 Yapay Zeka, last 20 Teknoloji Trendleri & Girişimcilik)
    for i in range(25):
        days_ago = 50 - i * 1.8
        pub_date = now - timedelta(days=days_ago, hours=random.randint(0, 12))
        if i < 5:
            topic = "Yapay Zeka"
        else:
            topic = "Teknoloji Trendleri" if i % 3 != 0 else "Girişimcilik"
        kw = random.sample(TOPIC_KEYWORDS[topic], 3)
        title = f"{topic}: {kw[0].capitalize()} lansmanı ve {kw[1]} analizi"
        tags = [f"#{t.replace(' ', '')}" for t in kw] + [f"#{topic.replace(' ', '')}"]
        score = round(random.gauss(5.9, 0.5), 2)

        posts.append({
            "schema_version": "1.0",
            "source": "demo_drift",
            "post_id": f"p_u2_{i:03d}",
            "user_id": "demo_user_02",
            "published_at_utc": pub_date.isoformat(),
            "timezone": "UTC",
            "timezone_inferred": True,
            "title": title,
            "description": f"Güncel pazar analizi ve trendler.",
            "tags": tags,
            "media_type": MediaTypeEnum.VIDEO.value if i % 2 == 0 else MediaTypeEnum.PHOTO.value,
            "media_available": True,
            "category_l1": topic,
            "category_l2": kw[0],
            "concept": kw[1],
            "latitude": None,
            "longitude": None,
            "user_followers": 980,
            "user_following": 510,
            "popularity_score": score,
            "image_embedding": generate_embedding(TOPICS.index(topic)),
            "text_embedding": generate_embedding(TOPICS.index(topic)),
            "ingested_at_utc": now.isoformat(),
        })

    # 3. Successful Reference Posts from other users for Qdrant and model training
    for i in range(120):
        days_ago = random.uniform(5, 90)
        pub_date = now - timedelta(days=days_ago, hours=random.randint(8, 22))
        topic = random.choice(TOPICS)
        kw = random.sample(TOPIC_KEYWORDS[topic], 3)
        title = f"{topic.capitalize()} liderlerinden {kw[0].capitalize()} üzerine ipuçları ve {kw[1]}"
        tags = [f"#{t.replace(' ', '')}" for t in kw] + [f"#{topic.replace(' ', '')}", "#EnSosyal"]
        # Make these top-quartile high-scoring posts
        score = round(random.uniform(6.1, 7.6), 2)

        posts.append({
            "schema_version": "1.0",
            "source": "smpd_benchmark",
            "post_id": f"smpd_{1000 + i}",
            "user_id": f"creator_{i % 20:02d}",
            "published_at_utc": pub_date.isoformat(),
            "timezone": "UTC",
            "timezone_inferred": True,
            "title": title,
            "description": f"Sosyal medyada viral olan başarılı {topic} paylaşımı.",
            "tags": tags,
            "media_type": random.choice([MediaTypeEnum.PHOTO.value, MediaTypeEnum.VIDEO.value]),
            "media_available": True,
            "category_l1": topic,
            "category_l2": kw[0],
            "concept": kw[1],
            "latitude": round(41.0082 + random.uniform(-0.1, 0.1), 4),
            "longitude": round(28.9784 + random.uniform(-0.1, 0.1), 4),
            "user_followers": random.randint(5000, 50000),
            "user_following": random.randint(200, 800),
            "popularity_score": score,
            "image_embedding": generate_embedding(TOPICS.index(topic)),
            "text_embedding": generate_embedding(TOPICS.index(topic)),
            "ingested_at_utc": now.isoformat(),
        })

    return posts


def main():
    raw_posts = generate_posts()
    df = pd.DataFrame(raw_posts)

    # Compute strictly chronological prior stats (no data leakage)
    df = compute_leakage_free_history(df, default_popularity_mean=5.5)

    # Validate each row against strict PostRecord schema
    records = []
    for _, row in df.iterrows():
        record_dict = row.to_dict()
        record_dict["tags"] = list(record_dict["tags"])
        record_dict["published_at_utc"] = pd.to_datetime(record_dict["published_at_utc"]).to_pydatetime()
        record_dict["ingested_at_utc"] = pd.to_datetime(record_dict["ingested_at_utc"]).to_pydatetime()
        if record_dict["image_embedding"] is not None:
            record_dict["image_embedding"] = list(record_dict["image_embedding"])
        if record_dict["text_embedding"] is not None:
            record_dict["text_embedding"] = list(record_dict["text_embedding"])
        record_dict["media_type"] = MediaTypeEnum(record_dict["media_type"])
        rec = PostRecord(**record_dict)
        records.append(rec)

    # Save to Parquet
    parquet_path = DATA_DIR / "posts.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"Saved {len(df)} validated post records to {parquet_path}")

    # Save demo accounts
    demo_path = ARTIFACTS_DIR / "demo_accounts.json"
    with open(demo_path, "w", encoding="utf-8") as f:
        json.dump(DEMO_ACCOUNTS, f, indent=2, ensure_ascii=False)
    print(f"Saved demo accounts to {demo_path}")


if __name__ == "__main__":
    main()
