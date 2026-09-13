"""
Canonical Taxonomy Service (G2)
Provides a versioned canonical taxonomy mapping SMPD categories to 11 platform-independent canonical categories.
"""

import math
import re
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd

# 1. Versioned dict mapping category -> list of subcategories
CANONICAL_TAXONOMY_V1: Dict[str, List[str]] = {
    "technology": ["artificial_intelligence", "software", "hardware", "consumer_electronics", "cybersecurity"],
    "automotive": ["cars", "electric_vehicles", "motorsports", "commercial_transport"],
    "fashion_beauty": ["apparel", "footwear", "luxury_style", "cosmetics_skincare"],
    "travel_tourism": ["destinations", "outdoor_adventure", "hospitality_hotels", "cultural_tourism"],
    "food_dining": ["culinary_recipes", "beverages_coffee", "restaurants_bars", "baking"],
    "entertainment_gaming": ["video_games", "cinema_tv", "music_concerts", "comics_animation"],
    "sports_fitness": ["fitness_training", "team_sports", "individual_sports", "extreme_sports"],
    "nature_wildlife": ["wild_animals", "domestic_pets", "landscapes", "botany_plants"],
    "art_design": ["architecture", "graphic_design", "fine_arts", "photography_style"],
    "business_economy": ["entrepreneurship", "personal_finance", "real_estate", "markets"],
    "social_lifestyle": ["family_parenting", "relationships", "daily_life", "celebrations_events"]
}

# 2. List of category names
CANONICAL_CATEGORIES: List[str] = list(CANONICAL_TAXONOMY_V1.keys())

# 3. Category code mapping (0-10)
CATEGORY_CODE_MAP: Dict[str, int] = {cat: idx for idx, cat in enumerate(CANONICAL_CATEGORIES)}

# Inverse mapping, for reporting and for rebuilding legacy features from codes.
CANONICAL_BY_CODE: Dict[int, str] = {code: name for name, code in CATEGORY_CODE_MAP.items()}


def canonical_name(code: int) -> str:
    """Canonical category name for a code (falls back to the classifier default)."""
    return CANONICAL_BY_CODE.get(int(code), "social_lifestyle")

# 4. Subcategory code mapping
SUBCATEGORY_CODE_MAP: Dict[str, int] = {}
_subcat_idx = 0
for cat, subcats in CANONICAL_TAXONOMY_V1.items():
    for subcat in subcats:
        SUBCATEGORY_CODE_MAP[subcat] = _subcat_idx
        _subcat_idx += 1

# 4b. Canonical category <-> tag-domain bridge (plan §3.1).
#
# The two taxonomies used different names ("canonical category" from post
# classification, "tag domain" from the hashtag keyword bank), so "is this tag
# aligned with the post?" used to compare `technology` against `tech_software`
# and always answer "no". This is the single source of truth for that bridge.
#
# `automotive` intentionally maps to no tag domain: the 12-domain hashtag bank
# has no automotive vocabulary, so a `#cars` tag is `unknown` rather than
# silently "misaligned".
CANONICAL_TO_TAG_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "technology": ("tech_software",),
    "automotive": (),
    "fashion_beauty": ("beauty_cosmetics", "fashion_apparel"),
    "travel_tourism": ("travel_tourism",),
    "food_dining": ("food_beverage",),
    "entertainment_gaming": ("gaming_esports", "art_entertainment"),
    "sports_fitness": ("sports_fitness",),
    "nature_wildlife": ("nature_wildlife",),
    "art_design": ("art_entertainment", "urban_architecture"),
    "business_economy": ("business_finance",),
    "social_lifestyle": ("social_events",),
}

TAG_DOMAIN_TO_CANONICAL: Dict[str, str] = {}
for _canonical, _domains in CANONICAL_TO_TAG_DOMAINS.items():
    for _domain in _domains:
        TAG_DOMAIN_TO_CANONICAL[_domain] = _canonical


def tag_domains_for_category(category: str | int | float | None) -> Tuple[str, ...]:
    """Returns the tag domains that count as aligned for a canonical category.

    Accepts the canonical name ("technology"), its integer code (0) or the
    integral float pandas hands back from a feature column (0.0). Unknown inputs
    return an empty tuple: alignment then degrades to `unknown` instead of
    pretending the tag is misaligned.
    """
    if category is None or isinstance(category, bool):
        return ()
    if isinstance(category, float):
        if not category.is_integer():
            return ()
        category = int(category)
    if isinstance(category, int):
        name = CANONICAL_BY_CODE.get(category)
        return CANONICAL_TO_TAG_DOMAINS.get(name, ()) if name else ()
    return CANONICAL_TO_TAG_DOMAINS.get(str(category).strip().lower(), ())


def canonical_for_tag_domain(domain: str) -> str | None:
    """Returns the canonical category a tag domain belongs to (inverse bridge)."""
    return TAG_DOMAIN_TO_CANONICAL.get(str(domain).strip().lower())

# 5. Mapping from SMPD's original categories/subcategories/concepts to canonical categories
# This is a basic keyword mapping. Depending on SMPD categories, this can be expanded.
SMPD_TO_CANONICAL_MAPPING: Dict[str, Tuple[str, str]] = {
    "yapay zeka": ("technology", "artificial_intelligence"),
    "yapayzeka": ("technology", "artificial_intelligence"),
    "derin öğrenme": ("technology", "artificial_intelligence"),
    "üretken": ("technology", "artificial_intelligence"),
    "teknoloji": ("technology", "consumer_electronics"),
    "yazılım": ("technology", "software"),
    "tech": ("technology", "consumer_electronics"),
    "ai": ("technology", "artificial_intelligence"),
    "software": ("technology", "software"),
    # Turkish tech terms (corpus-neutral: near-zero English-title collisions)
    "python": ("technology", "software"),
    "kodlama": ("technology", "software"),
    "hardware": ("technology", "hardware"),
    "cars": ("automotive", "cars"),
    "auto": ("automotive", "cars"),
    # NOTE: plain "ev" must NOT map to electric_vehicles - Turkish "ev" (home)
    # collides with English "EV"; electric vehicle content is matched below.
    "elektrikli": ("automotive", "electric_vehicles"),
    "fashion": ("fashion_beauty", "apparel"),
    "beauty": ("fashion_beauty", "cosmetics_skincare"),
    "travel": ("travel_tourism", "destinations"),
    "hotel": ("travel_tourism", "hospitality_hotels"),
    "food": ("food_dining", "culinary_recipes"),
    "cooking": ("food_dining", "culinary_recipes"),
    "restaurant": ("food_dining", "restaurants_bars"),
    "gaming": ("entertainment_gaming", "video_games"),
    "oyun": ("entertainment_gaming", "video_games"),
    "movies": ("entertainment_gaming", "cinema_tv"),
    "music": ("entertainment_gaming", "music_concerts"),
    "sports": ("sports_fitness", "team_sports"),
    "spor": ("sports_fitness", "team_sports"),
    # Turkish sports terms ("koşu" intentionally omitted: prefix-matches "koşullar")
    "futbol": ("sports_fitness", "team_sports"),
    "basketbol": ("sports_fitness", "team_sports"),
    "voleybol": ("sports_fitness", "team_sports"),
    "maraton": ("sports_fitness", "individual_sports"),
    "antrenman": ("sports_fitness", "fitness_training"),
    "güreş": ("sports_fitness", "team_sports"),
    "wrestling": ("sports_fitness", "team_sports"),
    "boks": ("sports_fitness", "team_sports"),
    "voleybol": ("sports_fitness", "team_sports"),
    "tenis": ("sports_fitness", "individual_sports"),
    "yüzme": ("sports_fitness", "individual_sports"),
    "bisiklet": ("sports_fitness", "individual_sports"),
    "atletizm": ("sports_fitness", "individual_sports"),
    "jimnastik": ("sports_fitness", "individual_sports"),
    "basketbol": ("sports_fitness", "team_sports"),
    "fitness": ("sports_fitness", "fitness_training"),
    "nature": ("nature_wildlife", "landscapes"),
    "pets": ("nature_wildlife", "domestic_pets"),
    "art": ("art_design", "fine_arts"),
    "design": ("art_design", "graphic_design"),
    "sanat": ("art_design", "fine_arts"),
    "fotoğraf": ("art_design", "photography_style"),
    "müzik": ("entertainment_gaming", "music_concerts"),
    "business": ("business_economy", "entrepreneurship"),
    "finance": ("business_economy", "personal_finance"),
    "finans": ("business_economy", "personal_finance"),
    "borsa": ("business_economy", "personal_finance"),
    "kripto": ("business_economy", "personal_finance"),
    "yatırım": ("business_economy", "personal_finance"),
    "girişim": ("business_economy", "entrepreneurship"),
    "economy": ("business_economy", "markets"),
    "lifestyle": ("social_lifestyle", "daily_life"),
    "family": ("social_lifestyle", "family_parenting"),
    "aile": ("social_lifestyle", "family_parenting"),
    "çocuk": ("social_lifestyle", "family_parenting"),
    "ev": ("social_lifestyle", "daily_life"),
    "hafta sonu": ("social_lifestyle", "daily_life"),
    "haftasonu": ("social_lifestyle", "daily_life"),
    "tatil": ("social_lifestyle", "daily_life"),
}

def _clean_optional_text(value: Any) -> Optional[str]:
    """Normalizes a taxonomy input to ``str | None``.

    Callers pass values straight out of a DataFrame, so missing entries arrive
    as ``NaN``/``pd.NA`` rather than ``None``; joining those into the search
    string used to raise instead of degrading to "no taxonomy input".
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NA:  # type: ignore[comparison-overlap]
        return None
    text = str(value).strip()
    return text or None


# 6. classify_post_category function
def classify_post_category(
    title: str,
    smpd_category: Optional[str],
    smpd_subcategory: Optional[str],
    smpd_concept: Optional[str]
) -> Dict[str, Any]:
    """
    Classify a post into the canonical taxonomy based on its title and SMPD categories.
    
    Args:
        title: Post title
        smpd_category: Original SMPD category
        smpd_subcategory: Original SMPD subcategory
        smpd_concept: Original SMPD concept
        
    Returns:
        dict containing:
        - primary_cat_code: int
        - primary_subcat_code: int
        - primary_category: str
        - primary_subcategory: str
        - primary_cat_confidence: float (deterministic match-density score, not a model probability)
        - has_secondary_cat: int (0/1)
        - secondary_category: str | None
        - secondary_subcategory: str | None
        - secondary_cat_confidence: float
    """
    # Create a searchable string from inputs
    inputs = filter(
        None,
        (
            _clean_optional_text(title),
            _clean_optional_text(smpd_category),
            _clean_optional_text(smpd_subcategory),
            _clean_optional_text(smpd_concept),
        ),
    )
    text_to_search = " ".join(inputs).lower()
    
    primary_match = None
    secondary_match = None
    match_count = 0
    
    # Heuristic matching: keywords of length >= 4 match as word PREFIXES so
    # Turkish inflections are covered ("güreş" matches "güreşi", "aile"
    # matches "ailemle"); shorter keywords must match whole words only, so
    # "ai" does not match inside "ailemle" and "ev" does not match inside
    # "evlilik". Turkish characters are word characters in Python regexes.
    # All matches are counted (no early break) so the confidence score stays
    # informative; assignment semantics are unchanged by later matches.
    for keyword, (cat, subcat) in SMPD_TO_CANONICAL_MAPPING.items():
        if len(keyword) >= 4:
            matched = re.search(rf"(?<!\w){re.escape(keyword)}", text_to_search)
        else:
            matched = re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text_to_search)
        if matched:
            match_count += 1
            if primary_match is None:
                primary_match = (cat, subcat)
            elif secondary_match is None and (cat, subcat) != primary_match:
                secondary_match = (cat, subcat)

            # No early break: keep scanning to count all keyword matches.
                
    # Fallback if no match
    if primary_match is None:
        primary_match = ("social_lifestyle", "daily_life")
        
    primary_cat, primary_subcat = primary_match
    
    # Deterministic match-density score (heuristic, NOT a trained-model
    # probability): 0.30 when nothing matched, up to 0.95 for many hits.
    primary_conf = 0.30 if match_count == 0 else round(min(0.95, 0.55 + 0.10 * match_count), 2)
    
    # Handle secondary category
    sec_cat = None
    sec_subcat = None
    sec_conf = 0.0
    
    if secondary_match:
        # Secondary confidence stays lower than the primary by construction.
        sec_conf = 0.45
        if sec_conf >= 0.40:
            sec_cat, sec_subcat = secondary_match
            
    return {
        "primary_cat_code": CATEGORY_CODE_MAP.get(primary_cat, 10),
        "primary_subcat_code": SUBCATEGORY_CODE_MAP.get(primary_subcat, 0),
        "primary_category": primary_cat,
        "primary_subcategory": primary_subcat,
        "primary_cat_confidence": primary_conf,
        "has_secondary_cat": 1 if sec_cat else 0,
        "secondary_category": sec_cat,
        "secondary_subcategory": sec_subcat,
        "secondary_cat_confidence": sec_conf
    }
