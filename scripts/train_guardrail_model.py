"""Trains the lightweight moderation guardrail classifier on real Turkish data.

Data sources:
- troff-v1.0.tsv.gz (Cagri Coltekin 2020, CC-BY; ~35k labeled Turkish tweets)
  https://coltekin.github.io/offensive-turkish/troff-v1.0.tsv.gz
- teamgzg/Datasets data1-7.csv (Apache-2.0; 709 profanity/insult/racist rows)
  https://github.com/teamgzg/Datasets
- Hand-written fallback corpus from backend.services.moderation_data

Outputs:
- artifacts/guardrail_classifier.joblib  (same path the runtime loads)
- artifacts/guardrail_metrics.json      (holdout metrics + suggested thresholds)
- data/processed/lexicon_candidates.json (data-derived lexicon candidates)
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import re
import urllib.request
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

try:
    from backend.services.moderation import AdversarialNormalizer, GemmaModerationGuardrail

    MODERATION_AVAILABLE = True
except ImportError:
    # backend/services/moderation.py is not shipped in every checkout
    # (.gitignore "Guardrail (WIP)"); the script still trains and calibrates,
    # only the real-evaluate battery validation is skipped.
    AdversarialNormalizer = None
    GemmaModerationGuardrail = None
    MODERATION_AVAILABLE = False

from backend.services.moderation_data import (
    FALSE_POSITIVE_BATTERY,
    MODERATION_TRAINING_CORPUS,
    UNSAFE_BATTERY,
    UNSAFE_LEXICON,
    strip_phrase_exceptions,
)

RAW_DIR = Path("data/raw/guardrail")
TEAMGZG_DIR = RAW_DIR / "teamgzg"
TROFF_GZ = RAW_DIR / "troff-v1.0.tsv.gz"
PROCESSED = Path("data/processed/guardrail_train.parquet")
MODEL_OUTPUT = Path("artifacts/guardrail_classifier.joblib")
METRICS_OUTPUT = Path("artifacts/guardrail_metrics.json")
LEXICON_CANDIDATES = Path("data/processed/lexicon_candidates.json")

TROFF_URL = "https://coltekin.github.io/offensive-turkish/troff-v1.0.tsv.gz"
TEAMGZG_URL = "https://raw.githubusercontent.com/teamgzg/Datasets/main/{file}"
TEAMGZG_FILES = {f"data{i}.csv": 0 for i in range(1, 8)}
TEAMGZG_EXPECTED_SIZES = {
    "data1.csv": 7071,
    "data2.csv": 24069,
    "data3.csv": 5896,
    "data4.csv": 6212,
    "data5.csv": 5100,
    "data6.csv": 7274,
    "data7.csv": 13426,
}
TROFF_EXPECTED_SIZE = 2_636_257
TROFF_EXPECTED_ROWS = 35_284

# teamgzg CSVs carry no label column; the label is implied by the file name
TEAMGZG_LABELS = {
    "data1.csv": "hate_speech",    # ırkçı
    "data2.csv": "sexual_content",  # küfür
    "data3.csv": "hate_speech",    # hakaret
    "data4.csv": "hate_speech",    # hakaret
    "data5.csv": "hate_speech",    # cinsiyetçi
    "data6.csv": "safe",           # diğer (non-offensive)
    "data7.csv": "hate_speech",    # hakaret
}

# troff label mapping: 'oth' (offense toward orgs/events) is deliberately
# dropped to avoid blocking legitimate criticism of companies/institutions
TROFF_LABEL_MAP = {
    "non": "safe",
    "prof": "sexual_content",
    "grp": "hate_speech",
    "ind": "hate_speech",
    "oth": None,
}

CAPS = {"safe": 4_500, "hate_speech": 4_500, "sexual_content": 1_500}
MIN_CLASS_TRAIN = 250  # floor for gambling/violence via template augmentation
ARTIFACT_MAX_BYTES = 10 * 1024 * 1024
SEED = 42

# Terms that look like lexicon hits but appear in legitimate text; safe rows
# containing them are always kept (hard negatives for the false-positive war)
FP_PROBE_TERMS = (
    "seksiyon", "promo", "promosyon", "poker", "5g", "3d", "e-ticaret",
    "patlıcan", "kebap", "menemen", "bahis konusu", "naked eye", "çıplak göz",
)

# Template augmentation for the small classes (train-only). These give the
# balanced LogisticRegression enough mass so gambling/violence probabilities
# do not fire spuriously on unrelated text.
GAMBLING_TERMS = [
    "bahis", "kumar", "casino", "rulet", "poker", "blackjack", "iddaa",
    "slot", "sweet bonanza", "canlı bahis", "kaçak iddaa", "kumarhane",
]
GAMBLING_FRAMES = [
    "güvenilir {t} sitesi", "{t} oyna para kazan", "{t} bonus fırsatları",
    "canlı {t} taktikleri", "{t} giriş adresi", "güncel {t} adresi",
    "{t} kuponları hazır", "yasadışı {t} oranları", "{t} para çekme yöntemleri",
    "en iyi {t} siteleri", "{t} nasıl oynanır", "{t} kazanç hesaplama",
    "gece {t} saatleri", "{t} strateji rehberi", "mobil {t} uygulaması",
    "{t} ve casino karşılaştırma", "{t} şikayet ve öneri", "{t} üyelik bonusu",
    "{t} canlı yayın izle", "{t} limitleri ve kurallar", "{t} deneme bonusu",
]
VIOLENCE_TERMS = [
    "intihar", "suicide", "eroin", "kokain", "metamfetamin", "uyuşturucu",
    "drugs", "heroin", "cocaine", "meth", "bomba yapımı", "silah satışı", "suikast",
]
VIOLENCE_FRAMES = [
    "{t} yöntemleri ve riskleri", "{t} temin etme yolları", "{t} etkileri ve zararları",
    "gizli {t} satışı", "{t} rehberi adım adım", "{t} kullananların hikayeleri",
    "{t} nereden bulunur", "{t} fiyatları ve piyasası", "{t} hakkında her şey",
    "{t} nasıl yapılır anlatım", "internetten {t} sipariş", "{t} planı detayları",
    "{t} ekipman listesi", "{t} dozaj tablosu", "{t} ve bağımlılık döngüsü",
    "{t} hakkında söylentiler", "{t} üretim rehberi", "{t} satın alma adımları",
    "{t} teknik bilgiler", "{t} gizlilik ipuçları",
]

# Inverse leetspeak for augmentation: letters that can be obfuscated
INV_LEET = {
    "a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7",
    "b": "8", "g": "9", "k": "q",
}
USER_AGENT = "npusula-guardrail-trainer/1.0"


def download_sources(force: bool = False) -> None:
    """Downloads datasets with stdlib urllib; skips when local size matches."""
    TEAMGZG_DIR.mkdir(parents=True, exist_ok=True)

    def fetch(url: str, dest: Path, expected_size: int) -> None:
        if dest.exists() and dest.stat().st_size == expected_size and not force:
            print(f"  {dest.name}: already present ({expected_size} bytes)")
            return
        print(f"  downloading {url} -> {dest.name}")
        part = dest.with_suffix(dest.suffix + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp, open(part, "wb") as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
        part.replace(dest)
        actual = dest.stat().st_size
        if actual != expected_size:
            raise RuntimeError(f"{dest.name}: expected {expected_size} bytes, got {actual}")

    fetch(TROFF_URL, TROFF_GZ, TROFF_EXPECTED_SIZE)
    for fname, expected in TEAMGZG_EXPECTED_SIZES.items():
        fetch(TEAMGZG_URL.format(file=fname), TEAMGZG_DIR / fname, expected)


def clean_text(text: str) -> str:
    """Light cleaning: strip URLs/@USER placeholders, collapse whitespace."""
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"@USER\w*", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().strip("\"'`")


def load_troff() -> pd.DataFrame:
    """Loads the 35k-row Turkish Offensive Language corpus."""
    with gzip.open(TROFF_GZ, "rt", encoding="utf-8") as f:
        df = pd.read_csv(f, sep="\t")
    assert list(df.columns) == ["id", "timestamp", "text", "label"], f"unexpected header: {df.columns}"
    assert len(df) == TROFF_EXPECTED_ROWS, f"expected {TROFF_EXPECTED_ROWS} rows, got {len(df)}"
    df = df.dropna(subset=["text"])
    df["text"] = df["text"].map(clean_text)
    df["label"] = df["label"].map(TROFF_LABEL_MAP)
    df = df.dropna(subset=["label"])
    df["source"] = "troff"
    df["priority"] = 1
    return df[["text", "label", "source", "priority"]]


def load_teamgzg() -> pd.DataFrame:
    """Loads teamgzg CSVs; label is implied by the file name."""
    frames = []
    for fname, label in TEAMGZG_LABELS.items():
        df = pd.read_csv(TEAMGZG_DIR / fname, on_bad_lines="warn")
        assert list(df.columns) == ["text"], f"{fname}: unexpected header {df.columns}"
        df["label"] = label
        df["source"] = f"teamgzg:{fname}"
        df["priority"] = 2
        frames.append(df[["text", "label", "source", "priority"]])
    merged = pd.concat(frames, ignore_index=True)
    merged["text"] = merged["text"].map(clean_text)
    assert len(merged) >= 700, f"teamgzg rows unexpectedly low: {len(merged)}"
    return merged


def load_hand_corpus() -> pd.DataFrame:
    """Loads the hand-written fallback corpus (sole source of gambling/violence)."""
    df = pd.DataFrame(MODERATION_TRAINING_CORPUS, columns=["text", "label"])
    df["text"] = df["text"].map(clean_text)
    df["source"] = "hand"
    df["priority"] = 0
    return df


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-source dedup on lowercased text; hand > troff > teamgzg."""
    df["key"] = df["text"].str.lower()
    df = df.sort_values("priority")
    df = df.drop_duplicates(subset="key", keep="first")
    return df.drop(columns=["key"])


def mine_hard_negatives(df: pd.DataFrame) -> pd.Series:
    """Safe rows containing lexicon terms or FP-probe terms are always kept."""
    lexicon_terms = "|".join(re.escape(t) for t in UNSAFE_LEXICON)
    probe_terms = "|".join(re.escape(t) for t in FP_PROBE_TERMS)
    pat = re.compile(rf"\b(?:{lexicon_terms}|{probe_terms})\b")
    return df["text"].str.lower().map(lambda t: bool(pat.search(t)))


def augment_templates() -> pd.DataFrame:
    """Template rows for gambling/violence so both classes exceed MIN_CLASS_TRAIN."""
    rows = []
    for term in GAMBLING_TERMS:
        for frame in GAMBLING_FRAMES:
            rows.append((frame.format(t=term), "gambling"))
    for term in VIOLENCE_TERMS:
        for frame in VIOLENCE_FRAMES:
            rows.append((frame.format(t=term), "violence"))
    df = pd.DataFrame(rows, columns=["text", "label"])
    df["source"] = "template"
    df["priority"] = 3
    df["is_synthetic"] = True
    return df


def augment_leetspeak(texts: list[str], frac: float = 0.15) -> list[str]:
    """Deterministically obfuscates a fraction of unsafe rows (train-only)."""
    rng = random.Random(SEED)
    out = []
    for text in texts:
        if rng.random() >= frac:
            out.append(text)
            continue
        chars = []
        for ch in text:
            if ch in INV_LEET and rng.random() < 0.35:
                chars.append(INV_LEET[ch])
            else:
                chars.append(ch)
        out.append("".join(chars))
    return out


def build_dataset() -> pd.DataFrame:
    """Loads all sources, cleans, dedupes, caps per class, marks hard negatives."""
    troff = load_troff()
    teamgzg = load_teamgzg()
    hand = load_hand_corpus()
    df = pd.concat([hand, troff, teamgzg], ignore_index=True)
    df = dedupe(df)
    df = df[df["text"].str.len() >= 5].reset_index(drop=True)
    df["hard_negative"] = (df["label"] == "safe") & mine_hard_negatives(df)
    print(f"merged corpus: {len(df)} rows "
          f"(hard negatives: {df['hard_negative'].sum()})")
    print("label counts before capping:")
    for label, cnt in df["label"].value_counts().items():
        print(f"  {label}: {cnt}")
    return df


def cap_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Subsamples per-class caps, keeping priority rows and hard negatives."""
    rng = np.random.default_rng(SEED)
    out = []
    for label, cap in CAPS.items():
        sub = df[df["label"] == label]
        if label == "safe":
            keep = sub[sub["hard_negative"]]
            rest = sub[~sub["hard_negative"]]
        elif label == "hate_speech":
            keep = sub[sub["source"].str.startswith("teamgzg")]
            rest = sub[~sub.index.isin(keep.index)]
        else:
            keep = sub.iloc[0:0]
            rest = sub
        remaining = cap - len(keep)
        if remaining > 0 and len(rest) > remaining:
            idx = rng.choice(rest.index, size=remaining, replace=False)
            keep = pd.concat([keep, rest.loc[idx]])
        elif remaining > 0:
            keep = pd.concat([keep, rest])
        out.append(keep)
    capped = pd.concat(out, ignore_index=True)
    print("label counts after capping:")
    for label, cnt in capped["label"].value_counts().items():
        print(f"  {label}: {cnt}")
    return capped


def fit_model(X_train: list[str], y_train: list[str]) -> Pipeline:
    """Fits the lightweight TF-IDF + LogisticRegression pipeline."""
    vectorizer = FeatureUnion(
        [
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, max_features=60_000)),
            ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, max_features=30_000)),
        ]
    )
    clf = LogisticRegression(C=1.0, max_iter=400, class_weight="balanced")
    pipe = Pipeline([("vec", vectorizer), ("clf", clf)])
    pipe.fit(X_train, y_train)
    return pipe


def holdout_metrics(pipe: Pipeline, X_hold: list[str], y_hold: list[str]) -> dict:
    """Per-class precision/recall/F1 plus macro-F1 on the holdout."""
    y_pred = pipe.predict(X_hold)
    report = classification_report(y_hold, y_pred, output_dict=True, zero_division=0)
    classes = sorted(set(y_hold))
    per_class = {
        label: {k: round(float(report[label][k]), 4) for k in ("precision", "recall", "f1-score", "support")}
        for label in classes
    }
    return {"per_class": per_class, "macro_f1": round(float(report["macro avg"]["f1-score"]), 4)}


def battery_gate_results(
    pipe: Pipeline,
    texts: list[str],
    u: float,
    r: float,
    f: float,
    o: float,
    labels: list[str] | None = None,
    obfuscated: list[bool] | None = None,
) -> dict:
    """Evaluates the ML gate (lexicon excluded) over a list of texts."""
    blocked, n_llm_band = 0, 0
    for i, text in enumerate(texts):
        obf = bool(obfuscated and obfuscated[i])
        stripped = strip_phrase_exceptions(text)
        probs = pipe.predict_proba([stripped])[0]
        classes = list(pipe.named_steps["clf"].classes_)
        scores = dict(zip(classes, probs))
        safe_prob = scores.get("safe", 0.5)
        risk = 1.0 - safe_prob
        unsafe = {k: v for k, v in scores.items() if k != "safe"}
        top_unsafe = max(unsafe.values()) if unsafe else 0.0
        decisive = top_unsafe >= u and risk >= r
        obf_unsafe = obf and top_unsafe >= o
        if decisive or obf_unsafe:
            blocked += 1
        elif risk >= f:
            n_llm_band += 1
    return {"blocked": blocked, "llm_band": n_llm_band, "total": len(texts)}


def calibrate_thresholds(pipe: Pipeline, X_hold: list[str], y_hold: list[str]) -> dict:
    """Grid search over (U, R, F) with hard constraints, maximizing unsafe recall."""
    classes = list(pipe.named_steps["clf"].classes_)
    probs = pipe.predict_proba([strip_phrase_exceptions(t) for t in X_hold])
    class_idx = {c: i for i, c in enumerate(classes)}
    safe_col = class_idx["safe"]

    # FP battery: clean texts, no lexicon hits by construction; assert it
    if MODERATION_AVAILABLE:
        normalizer = AdversarialNormalizer()
        for t in FALSE_POSITIVE_BATTERY:
            _, obf = normalizer.normalize(t)
            assert not obf, f"battery string unexpectedly obfuscated: {t!r}"

    hold_safe_idx = np.array([i for i, l in enumerate(y_hold) if l == "safe"])
    hold_unsafe_idx = np.array([i for i, l in enumerate(y_hold) if l != "safe"])
    n_safe_hold = len(hold_safe_idx)
    n_unsafe_hold = len(hold_unsafe_idx)

    battery_probs = pipe.predict_proba([strip_phrase_exceptions(t) for t in FALSE_POSITIVE_BATTERY])

    best = None
    for u in np.arange(0.50, 0.91, 0.05):
        for r in np.arange(0.50, 0.96, 0.05):
            for f in (0.40, 0.50, 0.60, 0.70):
                top_unsafe = probs[:, [i for i in range(len(classes)) if i != safe_col]].max(axis=1)
                risk = 1.0 - probs[:, safe_col]
                decisive = (top_unsafe >= u) & (risk >= r)
                # fail-open model: LLM band is not a block for ML-only metrics
                blocked_hold = decisive
                fp_safe = blocked_hold[hold_safe_idx].sum()
                tp_unsafe = blocked_hold[hold_unsafe_idx].sum()

                b_top = battery_probs[:, [i for i in range(len(classes)) if i != safe_col]].max(axis=1)
                b_risk = 1.0 - battery_probs[:, safe_col]
                battery_fp = int(((b_top >= u) & (b_risk >= r)).sum())

                if battery_fp > 0:
                    continue
                if n_safe_hold and fp_safe / n_safe_hold > 0.005:
                    continue
                unsafe_precision = tp_unsafe / max(blocked_hold.sum(), 1)
                if unsafe_precision < 0.95:
                    continue
                recall = tp_unsafe / max(n_unsafe_hold, 1)
                cand = {
                    "U": round(float(u), 2), "R": round(float(r), 2), "F": f,
                    "recall": round(float(recall), 4),
                    "fp_safe": int(fp_safe), "battery_fp": battery_fp,
                    "unsafe_precision": round(float(unsafe_precision), 4),
                }
                if best is None or (
                    cand["recall"] > best["recall"]
                    or (cand["recall"] == best["recall"] and cand["R"] > best["R"])
                ):
                    best = cand
    assert best is not None, "no threshold combination satisfied the hard constraints"
    best["llm_band_safe_frac"] = None  # filled below
    return best


def calibrate_obfuscated_threshold(
    pipe: Pipeline, X_hold: list[str], y_hold: list[str], best: dict
) -> dict:
    """Calibrates OBFUSCATED_UNSAFE_PROB on a synthetic obfuscated holdout."""
    normalizer = AdversarialNormalizer()
    classes = list(pipe.named_steps["clf"].classes_)
    safe_col = classes.index("safe")

    rng = random.Random(SEED + 7)
    safe_rows = [t for t, l in zip(X_hold, y_hold) if l == "safe"]
    unsafe_rows = [t for t, l in zip(X_hold, y_hold) if l != "safe"]

    def obfuscate(text: str) -> str:
        tokens = []
        for tok in text.split():
            if len(tok) >= 4 and re.fullmatch(r"[a-zçğıöşü]+", tok) and rng.random() < 0.6:
                mid = list(tok)
                for _ in range(1):
                    pos = rng.randrange(len(mid))
                    if mid[pos] in INV_LEET:
                        mid[pos] = INV_LEET[mid[pos]]
                tokens.append("".join(mid))
            else:
                tokens.append(tok)
        return " ".join(tokens)

    obf_unsafe = [obfuscate(t) for t in rng.sample(unsafe_rows, min(200, len(unsafe_rows)))]
    obf_safe = [obfuscate(t) for t in rng.sample(safe_rows, min(200, len(safe_rows)))]

    results = {}
    for o in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        res_safe = battery_gate_results(pipe, obf_safe, best["U"], best["R"], best["F"], o, obfuscated=[True] * len(obf_safe))
        res_unsafe = battery_gate_results(pipe, obf_unsafe, best["U"], best["R"], best["F"], o, obfuscated=[True] * len(obf_unsafe))
        results[o] = {
            "obf_safe_blocked": res_safe["blocked"],
            "obf_unsafe_blocked": res_unsafe["blocked"],
            "obf_unsafe_total": res_unsafe["total"],
        }
    # pick the lowest O with zero obfuscated-safe blocks; tie-break higher recall
    chosen = None
    for o in sorted(results):
        if results[o]["obf_safe_blocked"] == 0:
            chosen = o
            break
    if chosen is None:
        chosen = 0.80
    return {"O": chosen, "detail": {str(k): v for k, v in results.items()}}


def derive_lexicon_candidates(df: pd.DataFrame) -> dict:
    """Derives data-driven lexicon candidates from offensive vs safe text."""
    safe_docs = df[df["label"] == "safe"]["text"].str.lower()
    off_docs = df[df["label"] != "safe"]
    off_cat = dict(zip(off_docs["text"].str.lower(), off_docs["label"]))

    from collections import defaultdict
    term_safe = defaultdict(int)
    term_off = defaultdict(int)
    term_cat = defaultdict(lambda: defaultdict(int))

    for t in off_docs["text"].str.lower():
        for tok in set(re.findall(r"[a-zçğıöşü]+", t)):
            term_off[tok] += 1
            term_cat[tok][off_cat[t]] += 1
    for t in safe_docs:
        for tok in set(re.findall(r"[a-zçğıöşü]+", t)):
            term_safe[tok] += 1

    lexicon_set = set(UNSAFE_LEXICON)
    candidates = []
    for tok, n_off in term_off.items():
        if tok in lexicon_set or len(tok) < 3:
            continue
        n_safe = term_safe.get(tok, 0)
        if n_off < 8:
            continue
        prec = n_off / (n_off + n_safe)
        if prec < 0.90:
            continue
        majority = max(term_cat[tok], key=term_cat[tok].get)
        candidates.append({
            "term": tok,
            "n_offensive": n_off,
            "n_safe": n_safe,
            "precision": round(prec, 4),
            "suggested_category": "sexual_content" if majority == "prof" else "hate_speech",
            "score": round(prec * (1 + np.log1p(n_off)), 4),
        })
    candidates.sort(key=lambda c: -c["score"])
    return {"candidates": candidates[:500], "total": len(candidates)}


def _jsonable(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def train() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--skip-candidates", action="store_true")
    args = parser.parse_args()

    print("=== downloading sources ===")
    download_sources(force=args.force_download)

    print("=== building dataset ===")
    full_df = build_dataset()
    df = cap_dataset(full_df)

    train_df, hold_df = train_test_split(
        df, test_size=0.15, stratify=df["label"], random_state=SEED
    )
    assert not set(train_df["text"].str.lower()) & set(hold_df["text"].str.lower()), \
        "text overlap between train and holdout"
    print(f"split: train={len(train_df)}, holdout={len(hold_df)}")

    # Template augmentation + leetspeak augmentation (train-only)
    templates = augment_templates()
    X_train = train_df["text"].tolist()
    y_train = train_df["label"].tolist()
    unsafe_train_texts = [t for t, l in zip(X_train, y_train) if l != "safe"]
    unsafe_train_labels = [l for t, l in zip(X_train, y_train) if l != "safe"]
    X_train = X_train + templates["text"].tolist() + augment_leetspeak(unsafe_train_texts)
    y_train = y_train + templates["label"].tolist() + unsafe_train_labels
    assert len(X_train) == len(y_train), f"{len(X_train)} vs {len(y_train)}"
    for label in ("gambling", "violence"):
        assert y_train.count(label) >= MIN_CLASS_TRAIN, f"{label} below floor: {y_train.count(label)}"
    print(f"train rows after augmentation: {len(X_train)}")

    print("=== training model ===")
    pipe = fit_model(X_train, y_train)
    MODEL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, MODEL_OUTPUT)
    size_bytes = MODEL_OUTPUT.stat().st_size
    print(f"artifact saved: {MODEL_OUTPUT} ({size_bytes / 1024:.0f} KB)")
    assert size_bytes <= ARTIFACT_MAX_BYTES, f"artifact too large: {size_bytes}"

    X_hold = hold_df["text"].tolist()
    y_hold = hold_df["label"].tolist()

    print("=== holdout metrics ===")
    metrics = holdout_metrics(pipe, X_hold, y_hold)
    print(f"macro-F1: {metrics['macro_f1']}")
    for label, m in metrics["per_class"].items():
        print(f"  {label}: P={m['precision']} R={m['recall']} F1={m['f1-score']} n={m['support']}")

    print("=== threshold calibration ===")
    best = calibrate_thresholds(pipe, X_hold, y_hold)
    obf = calibrate_obfuscated_threshold(pipe, X_hold, y_hold, best)
    print(f"suggested: DECISIVE_UNSAFE_PROB={best['U']}, DECISIVE_RISK={best['R']}, "
          f"LLM_CHECK_RISK_FLOOR={best['F']}, OBFUSCATED_UNSAFE_PROB={obf['O']}")
    print(f"  unsafe recall={best['recall']}, precision={best['unsafe_precision']}, "
          f"holdout FP={best['fp_safe']}, battery FP={best['battery_fp']}")

    # Final validation through the real evaluate() with LLM forced unreachable
    if MODERATION_AVAILABLE:
        print("=== final battery validation (real evaluate, LLM unreachable) ===")
        guard = GemmaModerationGuardrail(api_url="http://127.0.0.1:9", timeout_seconds=0.5)
        fp_fails = [t for t in FALSE_POSITIVE_BATTERY if not guard.evaluate(t).is_safe]
        tp_misses = [(t, c) for t, c in UNSAFE_BATTERY if guard.evaluate(t).is_safe]
        print(f"  FP battery: {len(FALSE_POSITIVE_BATTERY) - len(fp_fails)}/{len(FALSE_POSITIVE_BATTERY)} pass")
        print(f"  unsafe battery: {len(UNSAFE_BATTERY) - len(tp_misses)}/{len(UNSAFE_BATTERY)} blocked")
        if fp_fails:
            print(f"  FP FAILURES: {fp_fails}")
        if tp_misses:
            print(f"  TP MISSES: {tp_misses}")
    else:
        print("=== moderation module unavailable in this checkout; "
              "skipping real-evaluate battery validation ===")
        fp_fails, tp_misses = [], []

    # Corpus hash for provenance
    corpus_hash = hashlib.sha256(
        ("\n".join(sorted(df["text"].str.lower())) + "\n".join(sorted(df["label"]))).encode("utf-8")
    ).hexdigest()[:16]

    report = {
        "corpus_hash": corpus_hash,
        "train_rows": len(X_train),
        "holdout_rows": len(X_hold),
        "class_counts_train": {l: y_train.count(l) for l in sorted(set(y_train))},
        "class_counts_holdout": {l: y_hold.count(l) for l in sorted(set(y_hold))},
        "holdout": metrics,
        "suggested_thresholds": {
            "DECISIVE_UNSAFE_PROB": best["U"],
            "DECISIVE_RISK": best["R"],
            "LLM_CHECK_RISK_FLOOR": best["F"],
            "OBFUSCATED_UNSAFE_PROB": obf["O"],
        },
        "calibration": _jsonable({**best, "obfuscated": obf["detail"]}),
        "artifact_bytes": size_bytes,
        "fp_battery_failures": fp_fails,
        "unsafe_battery_misses": tp_misses,
    }
    METRICS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(METRICS_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(_jsonable(report), f, ensure_ascii=False, indent=2)
    print(f"metrics saved: {METRICS_OUTPUT}")

    if not args.skip_candidates:
        print("=== lexicon candidates ===")
        cand = derive_lexicon_candidates(full_df)
        with open(LEXICON_CANDIDATES, "w", encoding="utf-8") as f:
            json.dump(_jsonable(cand), f, ensure_ascii=False, indent=2)
        print(f"candidates saved: {LEXICON_CANDIDATES} ({cand['total']} total, top {len(cand['candidates'])} kept)")


if __name__ == "__main__":
    train()
