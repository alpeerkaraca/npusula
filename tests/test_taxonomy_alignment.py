"""Canonical category <-> tag domain bridge and the alignment classes (plan §3.1)."""
import pytest

from backend.services.canonical_taxonomy import (
    CANONICAL_CATEGORIES,
    CANONICAL_TO_TAG_DOMAINS,
    CATEGORY_CODE_MAP,
    TAG_DOMAIN_TO_CANONICAL,
    canonical_for_tag_domain,
    classify_post_category,
    tag_domains_for_category,
)
from backend.services.tag_taxonomy import (
    TAG_CLASSES,
    TAXONOMY_CATEGORIES,
    align_tags,
    clean_and_filter_tags,
)


def test_canonical_to_tag_domain_bridge_is_complete_and_explicit():
    """Every canonical category maps onto the tag bank, and the named pairs hold."""
    assert set(CANONICAL_TO_TAG_DOMAINS) == set(CANONICAL_CATEGORIES)

    assert tag_domains_for_category("technology") == ("tech_software",)
    assert tag_domains_for_category("fashion_beauty") == ("beauty_cosmetics", "fashion_apparel")
    assert tag_domains_for_category("social_lifestyle") == ("social_events",)
    assert tag_domains_for_category("art_design") == ("art_entertainment", "urban_architecture")
    assert tag_domains_for_category("food_dining") == ("food_beverage",)
    assert tag_domains_for_category("entertainment_gaming") == ("gaming_esports", "art_entertainment")

    # Integer codes resolve to the same domains as their names.
    assert tag_domains_for_category(CATEGORY_CODE_MAP["technology"]) == ("tech_software",)
    assert tag_domains_for_category("no_such_category") == ()
    assert tag_domains_for_category(None) == ()


def test_every_tag_domain_has_exactly_one_canonical_owner():
    """The inverse bridge covers the whole 12-domain bank with no ambiguity."""
    assert set(TAG_DOMAIN_TO_CANONICAL) == set(TAXONOMY_CATEGORIES)
    for domain, canonical in TAG_DOMAIN_TO_CANONICAL.items():
        assert canonical in CANONICAL_CATEGORIES
        assert domain in CANONICAL_TO_TAG_DOMAINS[canonical]

    assert canonical_for_tag_domain("tech_software") == "technology"
    assert canonical_for_tag_domain("urban_architecture") == "art_design"
    assert canonical_for_tag_domain("unknown_domain") is None


def test_aligned_and_mismatched_are_distinguished_by_the_post_category():
    """`technology` post: #python is aligned, #makeup is mismatched (not 'irrelevant')."""
    result = align_tags(["#python", "#makeup", "#explore", "#porn", "#zzzz"], context_category="technology")

    assert result["aligned_semantic"] == ["python"]
    assert result["mismatched_semantic"] == ["makeup"]
    assert result["generic_promotional"] == ["explore"]
    assert result["nsfw_filtered"] == ["porn"]
    assert result["unknown"] == ["zzzz"]

    assert result["aligned_tag_count"] == 1.0
    assert result["mismatched_tag_count"] == 1.0
    assert result["unknown_tag_count"] == 1.0
    assert result["total_tag_count"] == 5
    assert result["semantic_tag_ratio"] == pytest.approx(0.2)
    assert set(result["tag_classes"].values()) <= set(TAG_CLASSES)


def test_fashion_post_accepts_both_of_its_domains():
    """`fashion_beauty` owns two tag domains; both count as aligned."""
    result = align_tags(["#makeup", "#outfit", "#python"], context_category="fashion_beauty")

    assert set(result["aligned_semantic"]) == {"makeup", "outfit"}
    assert result["mismatched_semantic"] == ["python"]


def test_unknown_tags_are_not_declared_meaningless():
    """A tag the bank has never seen is `unknown`, never `mismatched`/`generic`."""
    result = align_tags(["#nikon", "#canon", "#2024"], context_category="technology")

    assert result["unknown"] == ["nikon", "canon", "2024"]
    assert result["mismatched_semantic"] == []
    assert result["generic_promotional"] == []
    assert result["unknown_tag_ratio"] == pytest.approx(1.0)
    assert result["semantic_tag_ratio"] == 0.0


def test_alignment_without_context_does_not_invent_mismatches():
    """Without a category, matched tags cannot be called misaligned."""
    result = align_tags(["#python", "#makeup"])
    assert set(result["aligned_semantic"]) == {"python", "makeup"}
    assert result["mismatched_semantic"] == []


def test_dataframe_missing_values_do_not_break_classification():
    """Missing taxonomy values arrive as NaN, not None, when they come from a frame."""
    import numpy as np
    import pandas as pd

    frame = pd.DataFrame([{
        "title": "sabah kahvesi",
        "category_l1": None,
        "category_l2": np.nan,
        "concept": pd.NA,
    }])
    result = classify_post_category(
        frame.iloc[0]["title"],
        frame.iloc[0]["category_l1"],
        frame.iloc[0]["category_l2"],
        frame.iloc[0]["concept"],
    )

    assert result["primary_category"] in {"food_dining", "social_lifestyle"}
    assert result["primary_cat_confidence"] >= 0.30


def test_empty_and_invalid_inputs_are_safe():
    for payload in ([], None, "python", 42):
        result = align_tags(payload, context_category="technology")
        assert result["total_tag_count"] == 0
        assert result["aligned_semantic"] == []


def test_clean_and_filter_tags_keeps_only_aligned_semantics():
    aligned, noise_ratio = clean_and_filter_tags(
        ["#python", "#makeup", "#explore", "#2024"], context_category="technology"
    )

    assert aligned == ["python"]
    assert noise_ratio == pytest.approx(0.75)  # makeup + explore + 2024 are not usable


def test_category_classification_exposes_fallback_and_confidence():
    """Fallback, confidence and the secondary category are explicit, not implied."""
    matched = classify_post_category("Python ile yapay zeka", None, None, None)
    assert matched["primary_category"] == "technology"
    assert matched["primary_cat_confidence"] >= 0.55

    fallback = classify_post_category("zzzz", None, None, None)
    assert fallback["primary_category"] == "social_lifestyle"
    assert fallback["primary_cat_confidence"] == 0.30

    # Taxonomy columns can carry the category when the title is empty.
    from_taxonomy = classify_post_category("", "fashion", "Fashion", "glam")
    assert from_taxonomy["primary_category"] == "fashion_beauty"
    assert from_taxonomy["primary_subcategory"] in {"apparel", "cosmetics_skincare", "luxury_style"}

    two_domains = classify_post_category("spor ve müzik", None, None, None)
    assert two_domains["primary_category"] == "sports_fitness"
    assert two_domains["has_secondary_cat"] == 1
    assert two_domains["secondary_category"] == "entertainment_gaming"
    assert two_domains["secondary_cat_confidence"] < two_domains["primary_cat_confidence"]


def test_turkish_lifestyle_keyword_reaches_its_category():
    """The advisor's topic vocabulary is Turkish, so "Yaşam" needs the Turkish
    twin of "lifestyle" or that interest never reaches a category."""
    result = classify_post_category("Yaşam", None, None, None)
    assert result["primary_category"] == "social_lifestyle"
    assert result["primary_cat_confidence"] > 0.30


def test_prefix_matching_avoids_english_word_collisions():
    """"tech" must not match "techniques", nor "auto" match "automation".

    The prefix rule exists so Turkish inflections resolve; carried over to
    English stems it silently relabels unrelated posts.
    """
    assert (
        classify_post_category("dough techniques", None, None, None)["primary_category"]
        != "technology"
    )
    assert (
        classify_post_category("task automation for teams", None, None, None)[
            "primary_category"
        ]
        != "automotive"
    )
    # The Turkish inflections the prefix rule is for still resolve.
    assert (
        classify_post_category("yeni oyunu", None, None, None)["primary_category"]
        == "entertainment_gaming"
    )
    assert (
        classify_post_category("sabah sporu", None, None, None)["primary_category"]
        == "sports_fitness"
    )


def test_topic_decides_the_category_when_the_title_is_empty():
    """The declared topic must reach window scoring, not just the label.

    `_prepare_features` only ever classifies the post title, so on the live
    paths the category collapsed to the generic fallback and every topic
    produced identical windows.
    """
    from backend.services.recommendation import RecommendationService

    service = RecommendationService()
    codes = {}
    for topic in ("Oyun", "Yaşam"):
        _, code = service.predict_base_potential(
            user_prior_mean=5.8, user_post_count=0, title="", topic=topic
        )
        codes[topic] = code

    assert codes["Oyun"] == CATEGORY_CODE_MAP["entertainment_gaming"]
    assert codes["Yaşam"] == CATEGORY_CODE_MAP["social_lifestyle"]


def test_text_still_outranks_the_topic():
    """The topic describes the account; the text describes this post."""
    from backend.services.recommendation import RecommendationService

    service = RecommendationService()
    _, code = service.predict_base_potential(
        user_prior_mean=5.8, user_post_count=0, title="Python tutorial", topic="Spor"
    )
    assert code == CATEGORY_CODE_MAP["technology"]
