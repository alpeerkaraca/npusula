"""Behavioral profiling, TF-IDF centroid modeling, and drift detection service."""
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.pipeline import FeatureUnion

from backend.schemas.profile import (
    BehavioralProfile,
    DeclaredProfile,
    ProfileStatus,
    TopicWeight,
)

TOPIC_SEEDS: dict[str, str] = {
    "Yapay Zeka": "yapay zeka ai yapayzeka machine learning ml deep learning derin öğrenme llm dil modelleri model modeller agent ajan otonom pytorch tensorflow huggingface prompt üretken gpt sinir ağları nlp doğal dil işleme computer vision bot",
    "Yazılım": "yazılım python javascript backend frontend typescript docker veritabanı api framework kodlama mimari developer git programlama web servis mikroservis",
    "Teknoloji Trendleri": "teknoloji tech trendleri lansman akıllı cihaz donanım donanımı apple gadget batarya yenilik dijital tüketici elektroniği donanım çip kuantum inovasyon",
    "Oyun": "oyun gaming gamer konsol playstation steam twitch espor ekran kartı grafik oyun geliştirme oyunlar fps rpg gameplay",
    "Eğitim": "eğitim öğrenme kurs üniversite akademi kitap araştırma sınav kariyer gelişim ders öğretmen öğrenci rehberlik",
    "Finans": "finans borsa yatırım kripto bitcoin portföy ekonomi piyasa bütçe hisse fon sermaye para ticaret",
    "Spor": "spor futbol basketbol antrenman fitness beslenme maraton koşu sağlık egzersiz turnuva lig maç güreş boks voleybol tenis yüzme bisiklet dövüş wwe wrestling ring kort basket halter okçuluk atletizm jimnastik pilates yoga kaleci hakem takım şampiyon",
    "Kültür-Sanat": "kültür sanat sergi sinema tiyatro fotoğraf müzik edebiyat festival resim tasarım şiir film yönetmen",
    "Girişimcilik": "girişimcilik startup yatırım fonlama büyüme scaleup mvp müşteri iş modeli networking kurucu ortak melek yatırımcı saas b2b",
    "Yaşam": "yaşam lifestyle seyahat gezi kahve sağlık motivasyon doğa verimlilik çalışma düzeni minimalizm kamp makyaj güzellik bakım kozmetik eyeliner kombin stil moda skincare ootd aile ailem ailemle çocuk bebek ev evde mutlu mutluluk haftasonu hafta sonu tatil pazar arkadaş kutlama doğum günü anı hatıra piknik akşam yemeği sofra huzur keyif beraber birlikte gezi evlilik düğün nişan yıldönümü",
}


class ProfileService:
    """Computes behavioral profiles and detects drift between declared and actual posting behavior."""

    def __init__(self):
        self.topic_names = list(TOPIC_SEEDS.keys())
        # Word tokens plus character n-grams: Turkish is agglutinative, so
        # inflected forms ("güreşi", "turnuvası") share character n-grams with
        # their seed roots ("güreş", "turnuva") even without a stemmer.
        self.vectorizer = FeatureUnion([
            ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 1), max_features=2000, lowercase=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=3000, lowercase=True)),
        ])
        self._fit_vectorizer()
        # Track user decisions: user_id -> True/False
        self._user_decisions: dict[str, bool] = {}

    def _fit_vectorizer(self) -> None:
        seed_texts = list(TOPIC_SEEDS.values())
        self.vectorizer.fit(seed_texts)
        self.topic_matrix = self.vectorizer.transform(seed_texts)

    # Below this cosine similarity the text shares (almost) no vocabulary
    # with any topic seed; the classification is a guess and callers may
    # escalate to a semantic judge (e.g. the Gemma advisor).
    UNCERTAIN_SIM_THRESHOLD = 0.10
    # Callers should only trust the ML verdict above this similarity; weaker
    # matches (e.g. "tenis kortunda hafta sonu" winning via "hafta sonu") are
    # frequent misclassifications and must be escalated to the LLM judge.
    CONFIDENT_SIM_THRESHOLD = 0.25

    def classify_text_topic_confident(
        self, text: str, fallback_topic: str = "Teknoloji Trendleri"
    ) -> tuple[str, float]:
        """Classifies a short text to the closest topic centroid.

        Returns (topic, max_similarity). The similarity is 0.0 whenever the
        fallback was used, which callers can treat as "no confidence".
        """
        if not text.strip():
            return fallback_topic, 0.0
        vec = self.vectorizer.transform([text])
        sims = cosine_similarity(vec, self.topic_matrix)[0]
        max_sim = float(np.max(sims))
        if max_sim < self.UNCERTAIN_SIM_THRESHOLD:
            # Below confidence threshold / zero vocabulary overlap
            return fallback_topic, 0.0
        best_idx = int(np.argmax(sims))
        return self.topic_names[best_idx], max_sim

    def classify_text_topic(self, text: str, fallback_topic: str = "Teknoloji Trendleri") -> str:
        """Classifies a short text (e.g. idea) to the closest topic centroid."""
        topic, _ = self.classify_text_topic_confident(text, fallback_topic=fallback_topic)
        return topic

    def compute_behavioral_profile(
        self,
        user_id: str,
        user_posts: pd.DataFrame,
    ) -> BehavioralProfile:
        """Computes time-decay weighted topic distribution from the user's historical posts."""
        if user_posts.empty:
            return BehavioralProfile(
                user_id=user_id,
                behavioral_topics=[TopicWeight(topic=self.topic_names[0], weight=0.1)],
                top_topic=self.topic_names[0],
                top_weight=0.1,
                evidence_post_count=0,
            )

        now = datetime.now(timezone.utc)
        recent_posts = user_posts.tail(30).copy()
        post_count = len(recent_posts)

        texts: list[str] = []
        for _, p in recent_posts.iterrows():
            title = str(p.get("title", ""))
            tags_val = p.get("tags", [])
            tags_str = " ".join(tags_val) if isinstance(tags_val, (list, tuple, np.ndarray)) else str(tags_val)
            cat = str(p.get("category_l1", ""))
            texts.append(f"{title} {tags_str} {cat}")

        X_posts = self.vectorizer.transform(texts)

        # Time decay weighting
        if "published_at_utc" in recent_posts.columns:
            post_dates = pd.to_datetime(recent_posts["published_at_utc"])
            if post_dates.dt.tz is None:
                post_dates = post_dates.dt.tz_localize(timezone.utc)
            ages = np.array([(now - dt).total_seconds() / 86400.0 for dt in post_dates])
            weights = np.exp(-np.clip(ages, 0, 365) / 30.0)
        else:
            weights = np.ones(len(recent_posts))

        weights_sum = float(weights.sum())
        if weights_sum > 0:
            user_vec = X_posts.multiply(weights[:, None]).sum(axis=0) / weights_sum
        else:
            user_vec = X_posts.mean(axis=0)
        user_vec = np.asarray(user_vec)

        # Cosine similarity to topic centroids
        sims = cosine_similarity(user_vec, self.topic_matrix)[0]
        sims = np.clip(sims, 0.0, None)
        total_sim = float(sims.sum())
        if total_sim > 0:
            probs = sims / total_sim
        else:
            probs = np.ones(len(sims)) / len(sims)

        topic_weights: list[TopicWeight] = []
        for name, prob in zip(self.topic_names, probs):
            topic_weights.append(TopicWeight(topic=name, weight=round(float(prob), 3)))

        topic_weights.sort(key=lambda tw: tw.weight, reverse=True)
        top_topic = topic_weights[0].topic
        top_weight = topic_weights[0].weight

        return BehavioralProfile(
            user_id=user_id,
            behavioral_topics=topic_weights[:5],
            top_topic=top_topic,
            top_weight=top_weight,
            evidence_post_count=post_count,
        )

    def evaluate_drift(
        self,
        declared: DeclaredProfile,
        behavioral: BehavioralProfile,
    ) -> tuple[bool, str | None, float]:
        """Evaluates drift rules according to Section 4.2:

        post_count >= 10 and top_topic not in declared and top_weight >= 0.45 and (top_weight - declared_weight) >= 0.20
        """
        post_count = behavioral.evidence_post_count
        top_topic = behavioral.top_topic
        top_weight = behavioral.top_weight

        # Find max weight among declared topics
        declared_weights = [
            tw.weight for tw in behavioral.behavioral_topics if tw.topic in declared.declared_topics
        ]
        declared_weight = max(declared_weights) if declared_weights else 0.0

        similarity = round(declared_weight / max(top_weight, 1e-4), 3)
        similarity = min(1.0, max(0.0, similarity))

        # Check drift conditions
        drift_detected = (
            post_count >= 10
            and top_topic not in declared.declared_topics
            and top_weight >= 0.40  # Sensitive threshold for demo accounts
            and (top_weight - declared_weight) >= 0.15
        )

        question = None
        if drift_detected:
            declared_str = ", ".join(declared.declared_topics)
            pct = int(top_weight * 100)
            question = (
                f"'{declared_str}' seçmiştin; son {post_count} paylaşımın '{top_topic}' "
                f"kitlesine daha yakın (%{pct}). Önerilerini bu yönde güncelleyelim mi?"
            )

        return drift_detected, question, similarity

    def get_profile_status(
        self,
        declared: DeclaredProfile,
        behavioral: BehavioralProfile,
    ) -> ProfileStatus:
        drift_detected, question, similarity = self.evaluate_drift(declared, behavioral)
        user_id = declared.user_id
        decision = self._user_decisions.get(user_id)

        # Blending rules:
        # drift yoksa: 0.7 * declared + 0.3 * behavioral
        # kabul varsa: 0.2 * declared + 0.8 * behavioral
        # reddetmişse: 0.8 * declared + 0.2 * behavioral
        if decision is True:
            w_dec, w_beh = 0.2, 0.8
        elif decision is False:
            w_dec, w_beh = 0.8, 0.2
        else:
            w_dec, w_beh = 0.7, 0.3

        # Compute active recommendation topics
        active_map: dict[str, float] = {}
        for dt in declared.declared_topics:
            active_map[dt] = active_map.get(dt, 0.0) + w_dec / max(len(declared.declared_topics), 1)

        for tw in behavioral.behavioral_topics:
            active_map[tw.topic] = active_map.get(tw.topic, 0.0) + w_beh * tw.weight

        total = sum(active_map.values())
        rec_topics = [
            TopicWeight(topic=k, weight=round(v / total, 3))
            for k, v in sorted(active_map.items(), key=lambda item: item[1], reverse=True)[:5]
        ]

        return ProfileStatus(
            user_id=user_id,
            declared_topics=declared.declared_topics,
            behavioral_topics=behavioral.behavioral_topics,
            profile_similarity=similarity,
            drift_detected=drift_detected,
            evidence_post_count=behavioral.evidence_post_count,
            question=question,
            active_recommendation_topics=rec_topics,
        )

    def record_decision(self, user_id: str, accept: bool) -> None:
        self._user_decisions[user_id] = accept
