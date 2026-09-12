"""Tag cleaning, blacklist filtering, and 12-domain semantic taxonomy service.

Cleans noisy, non-informative tags (camera brands, years, numeric noise, NSFW terms)
and maps valid tags into 12 core semantic concept categories:
- beauty_cosmetics: eyeliner, makeup, beauty, lipstick, mascara, etc.
- tech_software: computer, technology, tech, python, coding, ai, etc.
- fashion_apparel: fashion, style, outfit, dress, shoes, etc.
- food_beverage: food, coffee, restaurant, dinner, wine, cake, etc.
- travel_tourism: travel, vacation, holiday, hotel, beach, tourism, etc.
- nature_wildlife: nature, landscape, animal, dog, bird, sunset, etc.
- sports_fitness: sport, fitness, gym, running, marathon, football, etc.
- business_finance: business, finance, money, crypto, startup, etc.
- art_entertainment: art, painting, design, music, concert, cinema, etc.
- urban_architecture: architecture, building, city, street, skyline, etc.
- social_events: people, family, wedding, party, birthday, event, etc.
- gaming_esports: game, gaming, gamer, playstation, steam, etc.
"""
from typing import Any
import math
import numpy as np

# Generic or promotional tags (discovery/promo)
GENERIC_PROMOTIONAL_TAGS: set[str] = {
    "explore", "viral", "followme", "picoftheday", "instagood", "instadaily",
    "follow", "like", "tagsforlikes", "repost", "daily", "bestoftheday",
    "vsco", "vscocam", "photooftheday", "instagram", "insta", "favorites",
    "fav", "top", "all", "day", "beautiful", "cute", "pretty", "nice",
    "awesome", "cool", "amazing", "love", "happy", "fun", "life", "good",
    "great", "perfect", "best", "moment", "photography", "photo", "photos",
    "photographer", "pic", "pics", "picture", "pictures", "image", "images",
    "shoot", "shot", "focus", "exposure", "composition", "macro"
}

# Hard-filtered NSFW/Adult noise
NSFW_TAGS: set[str] = {
    "sexy",
    "nude",
    "erotic",
    "porn",
    "nsfw",
    "lingerie",
    "boobs",
    "fetish",
    "feet",
    "babe",
}

# 12 Core Semantic Domains
TAXONOMY_MAP: dict[str, set[str]] = {
    "beauty_cosmetics": {
        "eyeliner",
        "makeup",
        "beauty",
        "lipstick",
        "mascara",
        "nailpolish",
        "cosmetics",
        "skincare",
        "eyeshadow",
        "blush",
        "foundation",
        "hair",
        "hairstyle",
        "salon",
        "spa",
        "glamour",
        "nails",
        "lash",
        "brows",
        "perfume",
    },
    "tech_software": {
        "computer",
        "technology",
        "tech",
        "software",
        "code",
        "coding",
        "developer",
        "programming",
        "python",
        "javascript",
        "typescript",
        "ai",
        "artificialintelligence",
        "machinelearning",
        "deeplearning",
        "robotics",
        "data",
        "cloud",
        "linux",
        "database",
        "docker",
        "hardware",
        "cyber",
        "web",
        "app",
        "digital",
        "internet",
        "server",
        "algorithm",
        "gadget",
        "electronics",
    },
    "fashion_apparel": {
        "fashion",
        "style",
        "outfit",
        "clothing",
        "dress",
        "shoes",
        "model",
        "portrait",
        "jewelry",
        "boots",
        "jacket",
        "streetwear",
        "runway",
        "accessories",
        "vintage",
        "wear",
        "look",
        "ootd",
        "jeans",
        "shirt",
        "hat",
        "bag",
        "glam",
    },
    "food_beverage": {
        "food",
        "foodporn",
        "instafood",
        "delicious",
        "yummy",
        "coffee",
        "tea",
        "cafe",
        "restaurant",
        "dinner",
        "lunch",
        "breakfast",
        "cake",
        "wine",
        "beer",
        "pizza",
        "burger",
        "recipe",
        "cooking",
        "kitchen",
        "chocolate",
        "fruit",
        "bread",
        "dessert",
        "cheese",
        "bakery",
        "cocktail",
        "chef",
    },
    "travel_tourism": {
        "travel",
        "trip",
        "vacation",
        "holiday",
        "tourism",
        "tourist",
        "destination",
        "hotel",
        "beach",
        "island",
        "resort",
        "explore",
        "adventure",
        "journey",
        "flight",
        "airport",
        "passport",
        "backpacking",
        "sightseeing",
        "wanderlust",
    },
    "nature_wildlife": {
        "nature",
        "landscape",
        "wildlife",
        "animal",
        "animals",
        "dog",
        "dogs",
        "cat",
        "cats",
        "bird",
        "birds",
        "flower",
        "flowers",
        "tree",
        "trees",
        "sunset",
        "sunrise",
        "sky",
        "sea",
        "ocean",
        "mountain",
        "mountains",
        "forest",
        "water",
        "river",
        "lake",
        "park",
        "garden",
        "tulip",
        "rose",
        "winter",
        "autumn",
        "spring",
        "summer",
    },
    "sports_fitness": {
        "sport",
        "sports",
        "fitness",
        "gym",
        "workout",
        "running",
        "marathon",
        "football",
        "soccer",
        "basketball",
        "tennis",
        "yoga",
        "cycling",
        "bike",
        "swimming",
        "skate",
        "skateboarding",
        "surf",
        "surfing",
        "ski",
        "snowboard",
        "athlete",
        "training",
        "climbing",
        "exercise",
        "crossfit",
    },
    "business_finance": {
        "business",
        "finance",
        "money",
        "investment",
        "investing",
        "stock",
        "stocks",
        "crypto",
        "bitcoin",
        "market",
        "economy",
        "startup",
        "entrepreneur",
        "marketing",
        "sales",
        "work",
        "office",
        "corporate",
        "management",
        "success",
        "trading",
        "b2b",
        "saas",
    },
    "art_entertainment": {
        "art",
        "artist",
        "artwork",
        "painting",
        "drawing",
        "illustration",
        "design",
        "graphicdesign",
        "music",
        "musician",
        "band",
        "concert",
        "festival",
        "cinema",
        "movie",
        "film",
        "theatre",
        "museum",
        "exhibition",
        "dance",
        "performance",
        "song",
        "guitar",
    },
    "urban_architecture": {
        "architecture",
        "building",
        "buildings",
        "urban",
        "city",
        "street",
        "bridge",
        "interior",
        "skyline",
        "house",
        "home",
        "interiordesign",
        "construction",
        "decor",
        "monument",
        "metropolis",
        "downtown",
    },
    "social_events": {
        "people",
        "family",
        "friends",
        "wedding",
        "bride",
        "groom",
        "party",
        "celebration",
        "birthday",
        "christmas",
        "xmas",
        "newyear",
        "halloween",
        "event",
        "crowd",
        "baby",
        "children",
        "gathering",
    },
    "gaming_esports": {
        "game",
        "gaming",
        "gamer",
        "playstation",
        "xbox",
        "nintendo",
        "steam",
        "esports",
        "rpg",
        "gameplay",
        "videogames",
        "cosplay",
        "twitch",
        "fps",
    },
}

TAXONOMY_CATEGORIES = list(TAXONOMY_MAP.keys())


def align_tags(
    tags: Any,
    context_category: str | None = None,
) -> dict:
    if not isinstance(tags, (list, tuple, np.ndarray)):
        return {
            "accepted_tags": [],
            "generic_tags": [],
            "rejected_tags": [],
            "nsfw_filtered_tags": [],
            "accepted_tag_count": 0.0,
            "generic_tag_count": 0.0,
            "rejected_tag_count": 0.0,
            "semantic_tag_ratio": 0.0,
            "irrelevant_tag_ratio": 0.0,
            "tag_alignment_mean": 0.0,
            "tag_alignment_min": 0.0,
            "tag_category_entropy": 0.0,
        }

    raw_tokens = [str(t).lower().strip().lstrip("#") for t in tags if str(t).strip()]
    if not raw_tokens:
        return {
            "accepted_tags": [],
            "generic_tags": [],
            "rejected_tags": [],
            "nsfw_filtered_tags": [],
            "accepted_tag_count": 0.0,
            "generic_tag_count": 0.0,
            "rejected_tag_count": 0.0,
            "semantic_tag_ratio": 0.0,
            "irrelevant_tag_ratio": 0.0,
            "tag_alignment_mean": 0.0,
            "tag_alignment_min": 0.0,
            "tag_category_entropy": 0.0,
        }

    accepted_tags = []
    generic_tags = []
    rejected_tags = []
    nsfw_filtered_tags = []
    alignment_scores = []
    cat_counts = {cat: 0 for cat in TAXONOMY_CATEGORIES}

    for token in raw_tokens:
        if token in NSFW_TAGS:
            nsfw_filtered_tags.append(token)
        elif token in GENERIC_PROMOTIONAL_TAGS:
            generic_tags.append(token)
        elif token.isnumeric() or len(token) <= 1:
            rejected_tags.append(token)
        else:
            matched_cats = [cat for cat, keywords in TAXONOMY_MAP.items() if token in keywords]
            if matched_cats:
                accepted_tags.append(token)
                score = 1.0 if (context_category is None or context_category in matched_cats) else 0.5
                alignment_scores.append(score)
                for cat in matched_cats:
                    cat_counts[cat] += 1
            else:
                rejected_tags.append(token)

    total_tokens = len(raw_tokens)
    accepted_count = len(accepted_tags)
    
    total_cat = sum(cat_counts.values())
    entropy_val = 0.0
    if total_cat > 0:
        probs = [c / total_cat for c in cat_counts.values()]
        entropy_val = -sum(p * math.log2(p) for p in probs if p > 0)

    return {
        "accepted_tags": accepted_tags,
        "generic_tags": generic_tags,
        "rejected_tags": rejected_tags,
        "nsfw_filtered_tags": nsfw_filtered_tags,
        "accepted_tag_count": float(accepted_count),
        "generic_tag_count": float(len(generic_tags)),
        "rejected_tag_count": float(len(rejected_tags)),
        "semantic_tag_ratio": float(accepted_count / total_tokens),
        "irrelevant_tag_ratio": float(len(rejected_tags) / total_tokens),
        "tag_alignment_mean": float(np.mean(alignment_scores)) if alignment_scores else 0.0,
        "tag_alignment_min": float(np.min(alignment_scores)) if alignment_scores else 0.0,
        "tag_category_entropy": float(entropy_val),
    }


def clean_and_filter_tags(tags: Any) -> tuple[list[str], float]:
    """Filters noisy, camera, platform, and blacklisted tags.

    Returns (clean_tags, blacklisted_ratio).
    """
    if not isinstance(tags, (list, tuple, np.ndarray)):
        return [], 0.0

    raw_tokens = [str(t).lower().strip().lstrip("#") for t in tags if str(t).strip()]
    if not raw_tokens:
        return [], 0.0

    res = align_tags(tags)
    raw_len = max(len(raw_tokens), 1)
    rejected_count = len(res["generic_tags"]) + len(res["rejected_tags"]) + len(res["nsfw_filtered_tags"])
    ratio = round(rejected_count / raw_len, 3)
    
    return res["accepted_tags"], ratio


def extract_concept_features(clean_tags: list[str]) -> dict[str, float]:
    """Calculates density/proportion across the 12 semantic concept categories."""
    if not clean_tags:
        return {f"concept_{cat}": 0.0 for cat in TAXONOMY_CATEGORIES}

    counts = {cat: 0 for cat in TAXONOMY_CATEGORIES}
    matched_total = 0

    for tag in clean_tags:
        for cat, keyword_set in TAXONOMY_MAP.items():
            if tag in keyword_set:
                counts[cat] += 1
                matched_total += 1

    denominator = max(matched_total, len(clean_tags), 1)
    return {f"concept_{cat}": round(counts[cat] / denominator, 4) for cat in TAXONOMY_CATEGORIES}


def get_dominant_concept(concept_features: dict[str, float]) -> tuple[str, int]:
    """Returns the dominant concept name and its integer ID (0 to 11)."""
    best_cat = "nature_wildlife"
    best_val = -1.0
    best_idx = 5  # default index

    for idx, cat in enumerate(TAXONOMY_CATEGORIES):
        val = concept_features.get(f"concept_{cat}", 0.0)
        if val > best_val:
            best_val = val
            best_cat = cat
            best_idx = idx

    if best_val <= 0.0:
        return "general", len(TAXONOMY_CATEGORIES)  # 12 is general

    return best_cat, best_idx
