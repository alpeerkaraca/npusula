import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.decomposition import TruncatedSVD

# Function words must not drive retrieval. Without this, a Turkish query whose
# only in-vocabulary token is a stray function word ("bir") retrieves
# unrelated posts at high similarity.
CONTEXT_STOP_WORDS: list[str] = sorted(
    set(ENGLISH_STOP_WORDS)
    | {
        "bir", "ile", "ve", "bu", "da", "de", "için", "çok", "daha", "en",
        "gibi", "kadar", "sonra", "önce", "ama", "ancak", "her", "ne", "ki",
        "mi", "var", "yok", "ise", "oldu", "olan", "olarak", "üzere", "şey",
        "ben", "sen", "biz", "siz", "onlar", "benim", "senin", "onun",
        "bizim", "sizin", "şu", "ya", "hem", "veya", "yani", "eğer", "göre",
        "başka", "tüm", "bütün", "az",
    }
)


class ContextEngine:
    """
    Independent context engine that produces content_context from post titles.
    Uses TF-IDF + TruncatedSVD as a lightweight proxy for a multilingual text encoder.
    """

    def __init__(self, svd_dim: int = 64):
        """
        Initialize the context engine.

        Args:
            svd_dim (int): Dimension of the output context embedding. Default is 64.
        """
        self.svd_dim = svd_dim
        self.vectorizer = TfidfVectorizer(
            max_features=10000, lowercase=True, stop_words=CONTEXT_STOP_WORDS
        )
        self.svd = TruncatedSVD(n_components=self.svd_dim, random_state=42)
        self.effective_dim = self.svd_dim
        self.is_fitted = False

    def fit(self, titles: list[str]) -> None:
        """
        Fits TF-IDF and TruncatedSVD on the provided training titles.

        Args:
            titles (list[str]): List of post titles for training.
        """
        valid_titles = [t if isinstance(t, str) and len(t.strip()) >= 3 else "" for t in titles]
        
        if not any(valid_titles):
            raise ValueError("ContextEngine requires at least one non-empty title.")
        tfidf_matrix = self.vectorizer.fit_transform(valid_titles)
        # Small fixture corpora cannot support the configured production dimension.
        # Fit the largest honest projection and zero-pad to the stable API dimension.
        self.effective_dim = max(1, min(self.svd_dim, tfidf_matrix.shape[0] - 1, tfidf_matrix.shape[1] - 1))
        self.svd = TruncatedSVD(n_components=self.effective_dim, random_state=42)
        self.svd.fit(tfidf_matrix)
        self.is_fitted = True

    def transform(
        self,
        title: str,
        smpd_category: str | None = None,
        smpd_subcategory: str | None = None,
        smpd_concept: str | None = None,
    ) -> dict:
        """
        Transform a single record to its context embedding and metadata.

        Priority order:
        - Title Context (Primary)
        - SMPD Taxonomy Context (Weak Supervision / Fallback)
        - Missing Context

        Args:
            title (str): Post title.
            smpd_category (str | None): SMPD Category.
            smpd_subcategory (str | None): SMPD Subcategory.
            smpd_concept (str | None): SMPD Concept.

        Returns:
            dict: Dictionary containing context_dim_* features, context_source_code, and missing_context_flag.
        """
        if not self.is_fitted:
            raise ValueError("ContextEngine is not fitted. Call fit() first.")

        text_to_encode = ""
        context_source_code = 2
        missing_context_flag = 1.0

        if isinstance(title, str) and len(title.strip()) >= 3:
            text_to_encode = title.strip()
            context_source_code = 0
            missing_context_flag = 0.0
        else:
            # Fallback to taxonomy
            taxonomy_parts = []
            if smpd_category:
                taxonomy_parts.append(str(smpd_category).strip())
            if smpd_subcategory:
                taxonomy_parts.append(str(smpd_subcategory).strip())
            if smpd_concept:
                taxonomy_parts.append(str(smpd_concept).strip())
            
            taxonomy_text = " ".join(taxonomy_parts).strip()
            if len(taxonomy_text) >= 3:
                text_to_encode = taxonomy_text
                context_source_code = 1
                missing_context_flag = 0.0

        # Encode text
        if text_to_encode:
            tfidf_vec = self.vectorizer.transform([text_to_encode])
            encoded = self.svd.transform(tfidf_vec)[0]
            embedding = np.zeros(self.svd_dim, dtype=np.float32)
            embedding[: len(encoded)] = encoded
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding /= norm
        else:
            # Zero vector for missing
            embedding = [0.0] * self.svd_dim

        # Prepare result
        result = {
            "context_source_code": context_source_code,
            "missing_context_flag": missing_context_flag,
        }
        for i in range(self.svd_dim):
            result[f"context_dim_{i}"] = embedding[i]

        return result

    def transform_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Batch transform a DataFrame.

        Args:
            df (pd.DataFrame): DataFrame containing 'title', 'smpd_category', 'smpd_subcategory', 'smpd_concept' columns.

        Returns:
            pd.DataFrame: DataFrame containing context dimensions and metadata flags.
        """
        results = []
        for _, row in df.iterrows():
            title = row.get("title", "")
            smpd_category = row.get("smpd_category")
            smpd_subcategory = row.get("smpd_subcategory")
            smpd_concept = row.get("smpd_concept")
            
            res = self.transform(title, smpd_category, smpd_subcategory, smpd_concept)
            results.append(res)
            
        return pd.DataFrame(results, index=df.index)

    def encode_titles(self, titles: list[str]) -> np.ndarray:
        """Vectorizes title text in one batch and returns normalized fixed-width vectors."""
        if not self.is_fitted:
            raise ValueError("ContextEngine is not fitted. Call fit() first.")
        cleaned = [str(title).strip() if title is not None else "" for title in titles]
        encoded = self.svd.transform(self.vectorizer.transform(cleaned))
        output = np.zeros((len(cleaned), self.svd_dim), dtype=np.float32)
        output[:, : encoded.shape[1]] = encoded
        norms = np.linalg.norm(output, axis=1, keepdims=True)
        np.divide(output, norms, out=output, where=norms > 0)
        return output

    def save(self, path: Path) -> None:
        """
        Save the fitted ContextEngine to disk.

        Args:
            path (Path): Path to save the model.
        """
        if not self.is_fitted:
            raise ValueError("ContextEngine is not fitted, nothing to save.")
        
        state = {
            "svd_dim": self.svd_dim,
            "vectorizer": self.vectorizer,
            "svd": self.svd,
            "effective_dim": self.effective_dim,
            "is_fitted": self.is_fitted
        }
        joblib.dump(state, path)

    def load(self, path: Path) -> None:
        """
        Load a fitted ContextEngine from disk.

        Args:
            path (Path): Path to load the model from.
        """
        state = joblib.load(path)
        self.svd_dim = state["svd_dim"]
        self.vectorizer = state["vectorizer"]
        self.svd = state["svd"]
        self.effective_dim = state.get("effective_dim", self.svd.n_components)
        self.is_fitted = state["is_fitted"]
