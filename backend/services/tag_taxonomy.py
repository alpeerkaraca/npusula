"""Tag cleaning, blacklist filtering, and 12-domain semantic taxonomy service.

`align_tags` classifies every tag as aligned / mismatched / generic / NSFW /
unknown **relative to the post's canonical category**, using the bridge defined
in `canonical_taxonomy.CANONICAL_TO_TAG_DOMAINS` (plan §3.1). Unknown tags are
tracked separately and are never reported as irrelevant.

The 12 core semantic concept domains:
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

from backend.services.canonical_taxonomy import tag_domains_for_category

# Generic or promotional tags (discovery/promo)
GENERIC_PROMOTIONAL_TAGS: set[str] = {
    "explore", "viral", "followme", "picoftheday", "instagood", "instadaily",
    "follow", "like", "tagsforlikes", "repost", "daily", "bestoftheday",
    "vsco", "vscocam", "photooftheday", "instagram", "insta", "favorites",
    "fav", "top", "all", "day", "beautiful", "cute", "pretty", "nice",
    "awesome", "cool", "amazing", "love", "happy", "fun", "life", "good",
    "great", "perfect", "best", "moment", "photography", "photo", "photos",
    "photographer", "pic", "pics", "picture", "pictures", "image", "images",
    "shoot", "shot", "focus", "exposure", "composition", "macro",
    # Turkish discovery/promo noise
    "keşfet", "takipet", "beğen", "paylaş",
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
    # Turkish equivalents
    "seksi",
    "ciplak",
    "çıplak",
    "erotik",
    "porno",
    "müstehcen",
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
        # Turkish
        "makyaj",
        "güzellik",
        "bakım",
        "cilt",
        "kozmetik",
        "saç",
        "tırnak",
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
        # Turkish
        "teknoloji",
        "yazılım",
        "yapayzeka",
        "kodlama",
        "donanım",
        "derinogrenme",
        "techtrends",
        "inovasyon",
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
        # Turkish
        "moda",
        "stil",
        "kombin",
        "giyim",
        "elbise",
        "çanta",
        "ayakkabı",
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
        # Turkish
        "yemek",
        "kahve",
        "çay",
        "tatlı",
        "tarif",
        "restoran",
        "kahvaltı",
        "mutfak",
        "ekmek",
        "çikolata",
        "meyve",
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
        # Turkish
        "seyahat",
        "gezi",
        "tatil",
        "otel",
        "plaj",
        "macera",
        "yolculuk",
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
        # Turkish
        "doğa",
        "manzara",
        "hayvan",
        "kedi",
        "köpek",
        "çiçek",
        "orman",
        "gökyüzü",
        "deniz",
        "günbatımı",
        "dağ",
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
        # Turkish
        "spor",
        "antrenman",
        "koşu",
        "güreş",
        "futbol",
        "basketbol",
        "voleybol",
        "boks",
        "yüzme",
        "bisiklet",
        "maç",
        "şampiyon",
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
        # Turkish
        "finans",
        "ekonomi",
        "yatırım",
        "borsa",
        "kripto",
        "girişim",
        "girişimcilik",
        "pazarlama",
        "para",
        "işdünyası",
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
        # Turkish
        "sanat",
        "müzik",
        "sinema",
        "tiyatro",
        "fotoğraf",
        "tasarım",
        "edebiyat",
        "konser",
        "kitap",
        "şiir",
        "kültür",
        # Turkish education/learning cluster (no dedicated domain in the 12)
        "eğitim",
        "öğrenme",
        "kişiselgelişim",
        "bilgi",
        "ders",
        "okul",
        "üniversite",
        "sınav",
        "kurs",
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
        # Turkish
        "mimari",
        "şehir",
        "sokak",
        "bina",
        "dekorasyon",
        "ev",
        "içmimari",
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
        # Turkish (generic lifestyle words land here pragmatically)
        "aile",
        "ailem",
        "ailemle",
        "düğün",
        "kutlama",
        "parti",
        "bebek",
        "çocuk",
        "arkadaş",
        "insanlar",
        "nişan",
        "anı",
        "mutluluk",
        "yaşam",
        "hayat",
        "günlükyaşam",
        "lifestyle",
        "ilham",
        "motivasyon",
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
        # Turkish
        "oyun",
        "oyuncu",
        "espor",
        "konsol",
    },
}

TAXONOMY_CATEGORIES = list(TAXONOMY_MAP.keys())


# Tag alignment classes (plan §3.1.3). "unknown" is deliberately its own class:
# a tag the dictionary has never seen is *unverified*, not *meaningless*, and
# conflating the two is what made the old "irrelevant tag" ratio untrustworthy.
TAG_CLASS_ALIGNED = "aligned_semantic"
TAG_CLASS_MISMATCHED = "mismatched_semantic"
TAG_CLASS_GENERIC = "generic_promotional"
TAG_CLASS_NSFW = "nsfw_filtered"
TAG_CLASS_UNKNOWN = "unknown"

TAG_CLASSES = (
    TAG_CLASS_ALIGNED,
    TAG_CLASS_MISMATCHED,
    TAG_CLASS_GENERIC,
    TAG_CLASS_NSFW,
    TAG_CLASS_UNKNOWN,
)


def _empty_alignment() -> dict:
    return {
        "aligned_semantic": [],
        "mismatched_semantic": [],
        "generic_promotional": [],
        "nsfw_filtered": [],
        "unknown": [],
        "tag_classes": {},
        "aligned_tag_count": 0.0,
        "mismatched_tag_count": 0.0,
        "generic_tag_count": 0.0,
        "nsfw_tag_count": 0.0,
        "unknown_tag_count": 0.0,
        "total_tag_count": 0,
        "semantic_tag_ratio": 0.0,
        "unknown_tag_ratio": 0.0,
        "tag_category_entropy": 0.0,
    }


def align_tags(
    tags: Any,
    context_category: str | int | None = None,
) -> dict:
    """Classifies every tag against the canonical category of the post.

    `context_category` is a canonical category name ("technology") or code (0) —
    the tag-domain bridge in `canonical_taxonomy.CANONICAL_TO_TAG_DOMAINS` maps
    it onto the 12 hashtag domains. A tag whose domain belongs to the post's
    category is `aligned_semantic`; a tag whose domain belongs to a *different*
    category is `mismatched_semantic`; a tag the bank does not know is `unknown`
    (kept as its own count, never reported as irrelevant).

    With no context category, matched tags cannot be judged mismatched and are
    reported as aligned; callers that need the mismatched class must pass a
    category (the advisor and training pipeline always do).
    """
    if not isinstance(tags, (list, tuple, np.ndarray)):
        return _empty_alignment()

    raw_tokens = [str(tag).lower().strip().lstrip("#") for tag in tags if str(tag).strip()]
    if not raw_tokens:
        return _empty_alignment()

    context_domains = tag_domains_for_category(context_category) if context_category is not None else None

    classes: dict[str, list[str]] = {name: [] for name in TAG_CLASSES}
    tag_classes: dict[str, str] = {}
    cat_counts = {cat: 0 for cat in TAXONOMY_CATEGORIES}

    for token in raw_tokens:
        if token in NSFW_TAGS:
            tag_class = TAG_CLASS_NSFW
        elif token in GENERIC_PROMOTIONAL_TAGS:
            tag_class = TAG_CLASS_GENERIC
        else:
            matched_cats = [cat for cat, keywords in TAXONOMY_MAP.items() if token in keywords]
            if not matched_cats:
                tag_class = TAG_CLASS_UNKNOWN
            elif context_domains is None or any(cat in context_domains for cat in matched_cats):
                tag_class = TAG_CLASS_ALIGNED
                for cat in matched_cats:
                    cat_counts[cat] += 1
            else:
                tag_class = TAG_CLASS_MISMATCHED
                for cat in matched_cats:
                    cat_counts[cat] += 1
        classes[tag_class].append(token)
        tag_classes[token] = tag_class

    total_tokens = len(raw_tokens)
    aligned_count = len(classes[TAG_CLASS_ALIGNED])

    total_cat = sum(cat_counts.values())
    entropy_val = 0.0
    if total_cat > 0:
        probs = [count / total_cat for count in cat_counts.values()]
        entropy_val = -sum(p * math.log2(p) for p in probs if p > 0)

    return {
        **classes,
        "tag_classes": tag_classes,
        "aligned_tag_count": float(aligned_count),
        "mismatched_tag_count": float(len(classes[TAG_CLASS_MISMATCHED])),
        "generic_tag_count": float(len(classes[TAG_CLASS_GENERIC])),
        "nsfw_tag_count": float(len(classes[TAG_CLASS_NSFW])),
        "unknown_tag_count": float(len(classes[TAG_CLASS_UNKNOWN])),
        "total_tag_count": total_tokens,
        "semantic_tag_ratio": float(aligned_count / total_tokens),
        "unknown_tag_ratio": float(len(classes[TAG_CLASS_UNKNOWN]) / total_tokens),
        "tag_category_entropy": float(entropy_val),
    }


def clean_and_filter_tags(tags: Any, context_category: str | int | None = None) -> tuple[list[str], float]:
    """Keeps only semantically aligned tags.

    Returns (aligned_tags, noise_ratio) where the noise ratio counts generic,
    NSFW and unknown tags — i.e. everything the classifier could not confirm
    for this post.
    """
    if not isinstance(tags, (list, tuple, np.ndarray)):
        return [], 0.0

    raw_tokens = [str(tag).lower().strip().lstrip("#") for tag in tags if str(tag).strip()]
    if not raw_tokens:
        return [], 0.0

    result = align_tags(tags, context_category=context_category)
    # Everything the classifier could not confirm for this post counts as noise,
    # including tags that belong to a different category.
    noise_count = len(raw_tokens) - len(result[TAG_CLASS_ALIGNED])
    return result[TAG_CLASS_ALIGNED], round(noise_count / max(len(raw_tokens), 1), 3)


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
