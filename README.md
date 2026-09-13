# N-Pusula (EnPusula)

EnSosyal için akıllı paylaşım zamanı danışmanı: bir içerik fikri verildiğinde
haftanın en iyi paylaşım pencerelerini, göreli potansiyelini ve önerilen
etiketleri üretir; ayrıca içerik güvenliği denetimi yapar.

## Ne yapar

- `POST /api/recommend/advisor` — fikri analiz eder: konu/kategori çıkarımı,
  benzer başarılı gönderiler, en iyi 3 zaman dilimi, kabul/red edilen
  etiketler ve Türkçe strateji açıklaması (Gemma 4)
- `GET /api/recommend/quick/{user_id}` — kullanıcının aktif konusuna göre
  hızlı ilk-3 öneri
- `GET /api/profile/{user_id}` — beyan edilen vs davranışsal profil + drift
- Tüm advisor istekleri içerik güvenliği guardrail'inden geçer
  (lexicon + hafif ML + LLM hakem; fail-open eşikler)

## Mimari

| Bileşen | Dosya | Rol |
|---|---|---|
| API | `backend/app.py` | FastAPI uçları |
| Popülerlik modeli | `backend/services/recommendation.py`, `artifacts/lgbm_popularity.txt` | LightGBM residual (36 feature): tahmin = hesap tabanı + içerik/zaman etkisi |
| Model eğitimi | `scripts/05_train_lgbm.py` | kronolojik 70/15/15; ablation B0/B1/M0–M5 |
| Hiperparametre arama | `scripts/tune_lgbm.py` | alt grup farkındalıklı rastgele arama |
| Vektör arama | `backend/services/retrieval.py` + Qdrant | benzer postlar + etiket ağırlıklandırma (benzerlik eşikli) |
| Konu/kategori | `backend/services/profile.py`, `backend/services/canonical_taxonomy.py` | char n-gram TF-IDF + kelime-sınırı eşleme; belirsizde Gemma yargıcı |
| Guardrail | `backend/services/moderation.py`, `moderation_data.py` | lexicon + TF-IDF/LogReg + Gemma hakem |
| LLM | `backend/services/gemma_advisor.py` | Ollama üzerinden Gemma 4 (konu, açıklama, hakemlik) |

## Veri durumu (önemli)

- Kaynak: **SMPD-Image (Flickr) train split** — 305.613 gerçek satır
- Dil: **%100 İngilizce** (305.613 başlığın tamamı ASCII; 0 Türkçe karakter)
- Zaman aralığı: 2015-02-28 – 2016-02-29 (tamamı gerçek kayıt)
- **Sentetik demo verisi kaldırıldı:** demo_user_* hesapları ve 55 fixture
  satırı veri setinden çıkarıldı; sistem yalnız gerçek SMPD kayıtlarıyla
  çalışır (`/api/demo-users` boş liste döner).
- **EnSosyal veri API'si talep edildi; sağlanması belirsiz.** Bu nedenle model ve
  demo SMPD benchmark'ı ile devam etmektedir. API sağlanırsa:
  1. `scripts/02_normalize_smp.py` → yeni veriyi normalize et
  2. `scripts/07_index_qdrant.py` → vektör indeksini yeniden kur
  3. `scripts/05_train_lgbm.py` → modeli yeniden eğit

  Guardrail korpusu bağımsızdır (troff + teamgzg), bu adımlardan etkilenmez.
- Türkçe fikirler için telafiler: Gemma konu yargıcı, retrieval benzerlik
  eşikleri ve etiket fallback'leri (bkz. `backend/services/retrieval.py`).
  Veri setinde Türkçe post bulunmadığından benzer-post listesi birçok Türkçe
  fikirde boş dönebilir; etiketler topic varsayılanlarına düşer.

## Sunum notları ve bilinen sınırlamalar

- Kategori çıkarımı **deterministik anahtar-kelime eşlemesidir** (eğitilmiş
  semantik sınıflandırıcı değil). `primary_cat_confidence` eşleşme yoğunluğuna
  dayanan sezgisel bir skordur (0.30 fallback – 0.95 çok eşleşme); **"AI güven
  skoru" olarak sunulmamalıdır.**
- Öneri motoru 7 × 24 = **168 aday saati** puanlar (yalnız prime-time saatler
  değil); en iyi üç slot `min_gap_hours=3` kuralıyla seçilir.
- Konu (topic) çıkarımı: kelime örtüşmesi zayıfsa Gemma yargıcı devreye girer;
  Gemma erişilemezse kullanıcı profilindeki konuya düşülür.
- Cold start (geçmişi olmayan hesap) modelin bilinen en zayıf grubudur
  (MAE ~1.94); bu grupta kazanç, veri/sinyal eksikliğinden kapalı bir kapıdır
  (bkz. deneysel sonuçlar).

## Çalıştırma

```bash
uvicorn backend.app:app                   # API (Qdrant ve Ollama opsiyonel; yoksa fallback)
pytest tests/                             # test paketi
python scripts/05_train_lgbm.py           # popülerlik modelini yeniden eğit
python scripts/train_guardrail_model.py   # guardrail modelini yeniden eğit
```

## Güncel metrikler (kronolojik test split'i)

| | Değer |
|---|---|
| LightGBM M5 (quantile α=0.55) | MAE 0.853, Spearman 0.870 |
| Kuyruk — en popüler %20 (viral) | MAE 1.082, sapma −0.70 |
| Baseline (B1) | MAE 1.148, Spearman 0.803 |
| Cold start (bilinen zayıf nokta) | MAE 1.94, Spearman 0.36 |
| Guardrail | holdout macro-F1 0.70; FP bataryası 25/25, unsafe bataryası 14/14 |

> Eğitim hedefi **quantile (α=0.55)**: viral içeriklerde (üst %20) tahmin sapmasını
> düşürüyor, karşılığında genel MAE ~%1.5 artıyor — bilinçli ödünleşim. Karar aynı
> kronolojik split'teki l1/q0.55/q0.60 karşılaştırmasıyla verildi; tablodaki tüm
> sayılar temiz veri (305.613 kayıt) üzerindendir. Ayrıntı: `artifacts/metrics.json`
> → `objective`, `tail`.

## Üçüncü taraf veriler

Bkz. `NOTICE.md` (SMPD, troff-v1.0, teamgzg, kelime listeleri ve lisansları).
