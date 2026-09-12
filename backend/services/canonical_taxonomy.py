"""
Canonical Taxonomy Service (G2)
Provides a versioned canonical taxonomy mapping SMPD categories to 11 platform-independent canonical categories.
"""

import re
from typing import Dict, List, Optional, Any, Tuple

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

# 4. Subcategory code mapping
SUBCATEGORY_CODE_MAP: Dict[str, int] = {}
_subcat_idx = 0
for cat, subcats in CANONICAL_TAXONOMY_V1.items():
    for subcat in subcats:
        SUBCATEGORY_CODE_MAP[subcat] = _subcat_idx
        _subcat_idx += 1

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
    "fitness": ("sports_fitness", "fitness_training"),
    "nature": ("nature_wildlife", "landscapes"),
    "pets": ("nature_wildlife", "domestic_pets"),
    "art": ("art_design", "fine_arts"),
    "design": ("art_design", "graphic_design"),
    "business": ("business_economy", "entrepreneurship"),
    "finance": ("business_economy", "personal_finance"),
    "finans": ("business_economy", "personal_finance"),
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
        - primary_cat_confidence: float
        - has_secondary_cat: int (0/1)
        - secondary_category: str | None
        - secondary_subcategory: str | None
        - secondary_cat_confidence: float
    """
    # Create a searchable string from inputs
    inputs = filter(None, [title, smpd_category, smpd_subcategory, smpd_concept])
    text_to_search = " ".join(inputs).lower()
    
    primary_match = None
    secondary_match = None
    
    # Word-boundary heuristic matching: a keyword matches only as a whole word,
    # so "ai" does not match inside "ailemle" and "ev" does not match inside
    # "evlilik". Turkish characters are word characters in Python regexes.
    for keyword, (cat, subcat) in SMPD_TO_CANONICAL_MAPPING.items():
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text_to_search):
            if primary_match is None:
                primary_match = (cat, subcat)
            elif secondary_match is None and (cat, subcat) != primary_match:
                secondary_match = (cat, subcat)

            if primary_match and secondary_match:
                break
                
    # Fallback if no match
    if primary_match is None:
        primary_match = ("social_lifestyle", "daily_life")
        
    primary_cat, primary_subcat = primary_match
    
    # Calculate a mock confidence
    primary_conf = 0.85 if smpd_category else 0.55
    
    # Handle secondary category
    sec_cat = None
    sec_subcat = None
    sec_conf = 0.0
    
    if secondary_match:
        # Dummy secondary confidence for demonstration
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
