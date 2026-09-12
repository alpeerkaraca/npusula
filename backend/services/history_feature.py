"""Leakage-free user history expanding feature generator."""
import numpy as np
import pandas as pd


def compute_leakage_free_history(df: pd.DataFrame, default_popularity_mean: float = 5.0) -> pd.DataFrame:
    """Computes prior post count and expanding mean popularity strictly before each post.

    Uses chronological sorting and shift(1) to guarantee zero target leakage from future or current posts.
    """
    if df.empty:
        return df

    out = df.copy()
    if "published_at_utc" in out.columns:
        out["published_at_utc"] = pd.to_datetime(out["published_at_utc"])
        out = out.sort_values(["user_id", "published_at_utc"]).reset_index(drop=True)
    else:
        out = out.sort_values(["user_id"]).reset_index(drop=True)

    g = out.groupby("user_id")["popularity_score"]

    # Number of posts strictly prior to this one
    out["user_post_count_prior"] = g.cumcount().astype(int)

    # Sum strictly prior to this post
    cumsum = g.cumsum()
    out["user_popularity_sum_prior"] = cumsum - out["popularity_score"].fillna(0.0)

    # Mean strictly prior to this post
    counts = out["user_post_count_prior"].replace(0, np.nan)
    prior_mean = out["user_popularity_sum_prior"] / counts
    out["user_popularity_mean_prior"] = prior_mean.fillna(default_popularity_mean).round(3)

    return out.drop(columns=["user_popularity_sum_prior"])
