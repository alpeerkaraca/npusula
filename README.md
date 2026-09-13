# N-Pusula (NPusula)

NSosyal için akıllı paylaşım zamanı danışmanı: bir içerik fikri verildiğinde
**önerilen paylaşım pencerelerini**, tarihsel gözlemsel liftini, güven seviyesini
ve önerilen etiketleri üretir; ayrıca içerik güvenliği denetimi yapar.

## Web arayüzü

Son Stitch tasarımlarına göre geliştirilen React/Vite uygulaması `frontend/` klasöründedir. Kurulum ve çalıştırma için [frontend/README.md](frontend/README.md) belgesine bakın. Arayüz varsayılan olarak mock modunda çalışır.

Arayüzün `/v1/pusula/*` sözleşmesi ile bu backend'in `/api/recommend/*` ve `/api/profile/*` uçları henüz eşlenmemiştir. HTTP modunu açmak tek başına entegrasyonu tamamlamaz; adaptör ve proxy yol eşlemesi uygulanmalıdır. Ayrıntılar: [entegrasyon belgesi](frontend/docs/backend-integration.md).

> **Dil sözleşmesi.** Sistem "kesin en iyi saat" iddia etmez. Çıktı, kanıt
> seviyesiyle birlikte bir **zaman penceresidir** ("Teknoloji içeriği için Salı
> 18.00–21.00 aralığı, geçmiş gözlemlerde desteklenen bir pencere"). Saat
> etkisi nedensel değil **gözlemseldir**; nedensellik iddiası ancak NSosyal
> A/B veya kontrollü keşif verisiyle kurulabilir.

## İki katmanlı model

```
Ham SMPD JSONL (yalnız gerçek kayıtlar)
  ↓ normalize + gerçek timezone dönüşümü      scripts/02_normalize_smp.py
posts.parquet
  ↓ kronolojik train / validation / kilitli test
  ├── Katman A — base-potential model         scripts/05_train_lgbm.py
  │     içerik + hesap geçmişi → genel popularity potansiyeli
  │     (zaman feature'ı YOK)
  └── Katman B — time-lift table              scripts/06_time_lift.py
        kategori × local weekday × 3 saatlik bucket
        → base modelden kalan residual lift + belirsizlik
  ↓ Inference
  ├── Post potansiyeli        (window'dan bağımsız tek sayı)
  ├── Önerilen zaman pencereleri (destek + güven + kanıt seviyesi)
  └── Güven / belirsizlik / cold-start uyarısı
```

**Katman A** yalnız içerik ve hesap geçmişini görür; `hour`, `weekday`, `month`,
döngüsel kodlamalar, `cat_x_hour`, `cat_x_weekday`, `history_x_hour` **yoktur**.
`account_baseline` hedefin *offset*'idir, model girdisi değildir.

**Katman B** "saat başarının sebebidir" demez. Yalnızca şunu söyler: *tarihsel
gözlemlerde, yeterli örnek bulunan bu kategori-zaman penceresi base potansiyele
göre pozitif residual lift göstermiştir.* Destek, kullanıcı bazlı bootstrap
aralığı ve hiyerarşik kanıt seviyesi her öneriyle birlikte döner.

## Ne yapar (API)

- `POST /api/recommend/advisor` — fikri analiz eder: konu/kategori çıkarımı,
  benzer başarılı gönderiler, önerilen pencereler, doğrulanmış etiketler ve
  Türkçe strateji açıklaması (Gemma 4). Gövdeye `timezone` (IANA) veya
  `utc_offset_minutes` eklenir; verilmezse pencereler UTC'de hesaplanır ve
  yanıt bunu `timezone_basis: "utc_fallback"` ile açıkça söyler.
- `GET /api/recommend/quick/{user_id}?timezone=Europe/Istanbul` — kullanıcının
  aktif konusuna göre hızlı pencere önerisi
- `GET /api/profile/{user_id}` — beyan edilen vs davranışsal profil + drift
- `POST /api/media/analyze` — yüklenen fotoğraf/videoyu CLIP ile analiz eder
  (konu, kanonik kategori, etiketler); dönen `media_id` advisor isteğine
  eklenince görsel kanıt öneriye girer
- Tüm advisor istekleri içerik güvenliği guardrail'inden geçer
  (lexicon + hafif ML + LLM hakem; fail-open eşikler)

## Mimari

| Bileşen | Dosya | Rol |
|---|---|---|
| API | `backend/app.py` | FastAPI uçları |
| Katman A — base potential | `backend/services/recommendation.py`, `artifacts/base_potential_lgbm.txt` | LightGBM residual (24 feature, zamansız): tahmin = hesap offset'i + içerik residual'ı |
| Katman B — time lift | `backend/services/time_lift.py`, `artifacts/time_lift_table.json` | 3 saatlik local bucket lift tablosu + hiyerarşik fallback + bootstrap CI |
| Aday pencereler | `backend/services/candidate_generator.py` | 7 gün × 8 pencere, kullanıcının **yerel** saatinde üretilir, UTC'ye çevrilir |
| Yerel zaman | `backend/services/time_features.py` | UTC→local dönüşümü, offset/IANA çözümü, bucket sözleşmesi |
| Model eğitimi | `scripts/05_train_lgbm.py` | kronolojik 70/15/15; ablation A0–A4 |
| Ayar (tuning) | `scripts/tune_lgbm.py` | **yalnız validation**: objective/alpha, hiperparametre, bucket boyutu, eşikler |
| Zaman lift tablosu | `scripts/06_time_lift.py` | yalnız train + expanding-window OOF residual |
| Kilitli final test | `scripts/evaluate_final.py` | test split'i **tek** kez okur; provenance yazar |
| Vektör arama | `backend/services/retrieval.py` + Qdrant | benzer postlar + etiket ağırlıklandırma (benzerlik eşikli) |
| Konu/kategori | `backend/services/profile.py`, `canonical_taxonomy.py` | char n-gram TF-IDF + kelime-sınırı eşleme; belirsizde Gemma yargıcı |
| Tag hizası | `backend/services/tag_taxonomy.py` | aligned / mismatched / generic / NSFW / **unknown** sınıfları |
| Guardrail | `backend/services/moderation.py`, `moderation_data.py` | lexicon + TF-IDF/LogReg + Gemma hakem |
| Medya analizi | `backend/services/media_analysis.py`, `models/` | CLIP ViT-B/32 zero-shot (video: 8 kare ortalaması) |
| LLM | `backend/services/gemma_advisor.py` | Ollama üzerinden Gemma 4 (konu, açıklama, hakemlik) |

**Runtime'da GPU/PyTorch tabular modeli yoktur.** Eski `pytorch_popularity_gpu.pt`
deneyi `artifacts/legacy/` altına alındı; `backend/models/tabular_nn.py` ve
`scripts/train_gpu_model.py` kaldırıldı. PyTorch yalnızca CLIP medya analizi ve
`device.py` cihaz raporlaması için kullanılır.

## Veri durumu

- Kaynak: **SMPD-Image (Flickr) train split** — 305.613 gerçek satır
- Dil: **%100 İngilizce** (305.613 başlığın tamamı ASCII; 0 Türkçe karakter)
- Zaman aralığı: 2015-02-28 – 2016-02-29 (tamamı gerçek kayıt)
- **Demo verisi yoktur ve giremez:** `demo_user_*` hesapları veri setinden
  çıkarıldı, normalizer önceki çıktıyı hiç okumaz ve her koşuda
  `assert (df["source"] == "smpd_real").all()` + `demo_row_count == 0` kapıları
  çalışır (`data/reports/data_quality.json`).
- **Timezone gerçek:** satırların %64'ünde kaynak offset vardır ve local
  saat/weekday bununla hesaplanır (`timezone_basis="source_offset"`); offset
  olmayan %36 satır `utc_fallback` olarak **işaretlenir**, yerel gibi
  sunulmaz. Bu ayrım `data_quality.json → timezone_basis_distribution` içinde
  raporlanır.
- **Medya dosyaları pakette yoktur:** `media_available` yalnız dosya gerçekten
  okunabiliyorsa `True` olur (bugün tüm satırlar `False`); kaynak statüsü
  alanı tek başına yeterli sayılmaz.
- **NSosyal veri API'si talep edildi; sağlanması belirsiz.** Bu nedenle model ve
  demo SMPD benchmark'ı ile devam etmektedir; adaptasyon planı için
  `docs/NSOSYAL_ADAPTATION.md`.
- Türkçe fikirler için telafiler: Gemma konu yargıcı, retrieval benzerlik
  eşikleri ve doğrulanmış etiket fallback'leri. SMPD korpusunda Türkçe post
  bulunmadığından benzer-post listesi birçok Türkçe fikirde boş döner.

## Kilitli final test sonuçları

Kaynak: `artifacts/final_evaluation.json`
(`split_protocol=chronological_train_validation_locked_test`,
`tuning_data=validation_only`, `test_touched_before_final=false`).
Split: train 213.929 / validation 45.842 / **test 45.842** (test yalnız burada okunur).

### B — Base potential (Layer A)

| | Değer |
|---|---|
| MAE | 1.095 |
| Medyan AE | 0.766 |
| Spearman | 0.804 |
| Pinball (α=0.6) | 0.513 |
| Sapma (bias) | +0.345 |
| Üst %20 kuyruk | MAE 1.354, sapma −1.145 |
| Baseline — hesap offset'i (A1) | MAE 1.148, Spearman 0.803 |
| Cold start (A3) | MAE 1.962, Spearman 0.383 |
| Very-low history | MAE 1.583, Spearman 0.672 |

> **Bu sayılar yalnız post popularity tahminidir — saat önerisi başarısı
> değildir.** İçerik modelinin hesap offset'ine kattığı MAE kazancı 0.053'tür
> (1.148 → 1.095); yakın bir dönemdeki (validation) kazanç 0.084 idi ve test
> penceresi farklı bir popularity seviyesinde (+0.345 sapma). Cold start hâlâ
> en zayıf gruptur.

### Aynı protokolde legacy karşılaştırması

| Varyant | Test MAE | Spearman |
|---|---|---|
| A3 (üretim, zamansız + 24 feature) | 1.095 | 0.804 |
| A4 — eski M5 vektörü (36 feature, zaman + offset girdi olarak) | 0.876 | 0.867 |
| A4 — offset girdisi çıkarılmış, yalnız zaman feature'ları | 1.117 | 0.806 |

> A4'ün düşük MAE'si **yayın saatini girdi olarak görmesinden** gelir — ürünün
> seçmesi gereken değişkenin ta kendisi — ve `account_baseline`'ı aynı anda hem
> offset hem girdi olarak kullanmasından. İkincisi çıkarıldığında A4 (1.117)
> üretim modelinin (1.095) gerisine düşer. Bu satır aynı protokolde bir
> karşılaştırma referansıdır, üretim adayı değildir.
> Eski `metrics.json` değeri (MAE 0.853) `artifacts/legacy/` altındadır ve
> **karşılaştırılabilir değildir**: farklı split protokolü ve aynı test seti
> tuning'de incelenmişti.

### C — Time lift (Layer B, held-out gözlemsel)

| | Değer |
|---|---|
| Desteklenen kategori×weekday×bucket grubu | 354 / 616 |
| NDCG@3 (bucket sıralaması) | 0.328 |
| Held-out bucket-lift MAE | 1.079 |
| Held-out bucket-lift Spearman (kategori içi) | 0.026 |
| Top-1 / top-3 gerçek-bucket isabeti | 0.136 / 0.373 |
| Top-1 pozitif-lift isabeti | 0.099 |
| Ortalama sıralama pişmanlığı (regret) | 0.414 |
| Bootstrap CI kapsama (nominal 0.90) | 0.311 |
| Önerilen pencere − destekli pencere taban çizgisi | **+0.004** |
| Tie / no-claim oranı | 0.995 |

> **Dürüst sonuç: zaman-lift katmanı bu korpusta kilitli test dönemine
> genelleşmiyor.** Validation'da taban çizgisine göre +0.118 olan fark test
> penceresinde +0.004'e düşüyor; NDCG@3 0.41 → 0.33, CI kapsaması 0.31
> (aralıklar dar). Bu nedenle sistem validation'da seçilmiş kurala sadık kalıp
> **vakaların %99.5'inde kesin sıralama yerine geniş pencere / no-claim**
> döndürüyor. Mutlak önerilen lift negatiftir (−0.32) ama "destekli herhangi
> bir pencere" taban çizgisi de negatiftir (−0.32): train tahminiyle seçilen
> grupların held-out'ta ortalamaya dönmesi (kazananın laneti) beklenen bir
> etkidir, bu yüzden yalnızca *fark* okunur.

### D — Ürün güven raporu

| | Oran |
|---|---|
| Yüksek güven | 0.5% |
| Orta güven | 0.0% |
| Düşük güven | 99.5% |
| Cold-start önerisi | 11.0% |
| UTC fallback önerisi | 32.6% |
| No-claim / geniş pencere | 99.5% |
| Yüksek güven verilen vakalarda pozitif lift isabeti | 0.085 |

> Güven kuralı (destek + CI sıfırdan ayrılması + anlamlı fark eşiği) bu veride
> neredeyse hiç sağlanmıyor. "Yüksek güven" vakaların isabeti taban orandan
> (~0.10) düşük; bu, kuralın kalibre olmadığının kanıtı olarak raporlanıyor,
> gizlenmiyor. Kullanıcıya gösterilen dil bu yüzden ağırlıklı olarak
> "saat etkisi belirgin değil" oluyor.

## Üretim komutları

```bash
# 1) Normalize + veri kalitesi/provenance raporu   -> data/processed/posts.parquet, data/reports/data_quality.json
python scripts/02_normalize_smp.py

# 2) Yalnız-validation ayarı (test okunmaz)        -> artifacts/tuning_results.json
python scripts/tune_lgbm.py

# 3) Katman A: train-only vocabulary + ablation    -> artifacts/base_potential_lgbm.txt,
#    A0-A4 (test okunmaz)                             artifacts/base_potential_metrics.json,
#                                                     artifacts/text_svd_model.joblib
python scripts/05_train_lgbm.py

# 4) Katman B: train OOF residual'larından tablo   -> artifacts/time_lift_table.json
python scripts/06_time_lift.py

# 5) Kilitli final test (TEK çalıştırma)           -> artifacts/final_evaluation.json
python scripts/evaluate_final.py

# 6) Retrieval indeksi (yalnız retrieval)          -> artifacts/qdrant_context_engine.joblib + Qdrant
python scripts/07_index_qdrant.py

# 7) Doğrulama
python scripts/verify_acceptance.py               # planın 12 kabul maddesi, artifact'lardan
pytest tests/                                     # 156 test
python scripts/smoke_test.py                      # canlı API uçtan uca
python scripts/idea_battery.py --base-url http://127.0.0.1:8000
```

`evaluate_final.py`, upstream artifact'lar `test_touched_before_final=false`
demiyorsa **çalışmayı reddeder**. Adımların sırası önemlidir: tuning/kilit
seçim test okunmadan tamamlanır.

## Sunum notları ve bilinen sınırlamalar

- Kategori çıkarımı **deterministik anahtar-kelime eşlemesidir** (eğitilmiş
  semantik sınıflandırıcı değil). `primary_category_confidence` eşleşme
  yoğunluğuna dayanan sezgisel bir skordur (0.30 fallback – 0.95 çok eşleşme);
  **"AI güven skoru" olarak sunulmamalıdır.** Hiçbir kelime eşleşmediyse yanıt
  `primary_category_is_fallback=true` döner ve tag hizası bir kategori
  *iddia etmeden* yapılır.
- Aday üretimi 7 gün × 24 saat taranır, ancak **ürün çıktısı 3 saatlik
  pencerelerdir**; saatler tek tek sıralanmaz.
- `relative_potential` **yüzde cinsinden kesin engagement artışı değildir**:
  aday pencereler arasında modelin gözlemsel göreli skorudur (lift farkı).
- Tag önerisi yalnız `aligned_semantic` etiketlerden üretilir; sözlükte
  bulunmayan etiket `unknown_tags` olarak ayrı raporlanır ("anlamsız" ilan
  edilmez).
- Konu (topic) çıkarımı: kelime örtüşmesi zayıfsa Gemma yargıcı devreye girer;
  Gemma erişilemezse kullanıcı profilindeki konuya düşülür.
- Medya analizi yalnızca **yüklenen dosya** üzerinde çalışır; korpustaki
  görsellerle karşılaştırma yapılmaz (veri paketinde görsel dosyası yok).
  Etiketler küratörlü bir bankadan gelir ve yalnızca görsel olarak ayırt
  edilebilir kavramları içerir (#kahve, #fitness); finans veya girişimcilik
  gibi soyut konular görselden çıkarılmaz, Gemma yargıcına bırakılır.
- Kişiselleştirilmiş `user × kategori × bucket` zaman katmanı **yoktur**:
  minimum destek ve shrinkage olmadan eklenmez (plan Faz 7).

## Medya analizi (fotoğraf / video)

`POST /api/media/analyze` (multipart `file`) yüklenen dosyayı CLIP ViT-B/32 ile
analiz eder ve bir `media_id` döner; bu id `POST /api/recommend/advisor`
gövdesine eklendiğinde görsel kanıt öneriye karışır.

| Adım | Davranış |
|---|---|
| Doğrulama | Görsel: jpeg/png/webp ≤ 10 MB · Video: mp4/mov/webm ≤ 50 MB ve ≤ 60 sn |
| Görsel | RGB → CLIP → L2 normalleştirilmiş 512-D vektör |
| Video | 8 eşit dilimin **merkezinden** kare (ilk/son siyah kare sorunu yapısal olarak oluşmaz) → embeddinglerin ortalaması → yeniden normalleştirme |
| Çıktı | konu, kanonik kategori (11), etiketler (≤3), güven ve marj |
| Konu merdiveni | Güvenli metin → güvenli görsel → Gemma yargıcı → kullanıcı profili |
| Kategori kuralı | Yalnızca metin hiçbir kelimeyle eşleşmediyse (güven 0.30) görsel kategorisi geçersiz kılar |
| Etiketler | Görsel etiketleri listebaşı olur, aynı hiza kontrolünden geçer |

Ölçülen süreler (CPU): görsel ~0.06 sn, 8 kareli video ~0.5 sn, model yükleme
~7 sn (açılışta bir kez).

**Eşik altındaysa "belirsiz" denir:** `topic` / `canonical_category` `null`
döner ve karar bir üst katmana bırakılır — argmax'ın sessizce ilk sınıfı
seçmesi HIKAYE.md Bölüm 9'da kayıtlı bir hataydı.

**Model feature sözleşmesi:** SMPD paketi medya dosyası dağıtmadığı için
(`flickr_smpd_dataset.md`) görsel embedding eğitim korpusuna **eklenmemiştir**;
görsel popularity feature'ı ancak dosyaları olan lisanslı/NSosyal bir korpusla
ayrı bir veri sözleşmesi ve yeniden eğitimle eklenebilir. Bugün görsel analiz
mevcut girdileri besler: kategori kolonları (doğrudan uygulanır) ve etiketler.

**Ağırlıklar yoksa:** `/api/media/analyze` 503 döner, `/api/health` içinde
`media_analyzer_ready: false` görünür; advisor metin-only çalışmaya devam eder.

**Not (GPU):** CLIP varsayılan olarak CPU'da koşar. `MEDIA_DEVICE=auto`
DirectML'i dener, ancak bu makinede torch-directml bu modeli çalıştıramıyor
(`Cannot set version_counter for inference tensor`) ve CPU'ya düşer; CPU
süreleri demo için fazlasıyla yeterlidir.

## Çalıştırma

### Docker Compose ile (önerilen / production)

Gereksinimler: Docker Desktop veya Podman + compose sağlayıcısı. Veri seti ve
model çıktıları container'a **bind-mount** edilir (`./data`, `./artifacts`);
ilk çalıştırmadan önce bir kez üretilmeleri gerekir.

```bash
docker compose up -d --build     # qdrant + ollama (+ model indirme) + api
docker compose logs -f api       # uygulama logları (LOG_LEVEL ile seviye)
```

İlk açılışta `ollama-init` hizmeti `GEMMA_MODEL_NAME` modelini (varsayılan
`gemma4:e4b`) otomatik indirir. İndirme tamamlanana kadar
LLM'e bağlı yollar (konu yargıcı, açıklama üretimi) deterministik
fallback'lerine düşer; API bu sırada da çalışır.

| Servis | Port | Not |
|---|---|---|
| `api` | 8000 (`API_PORT`) | `/api/health` healthcheck'i tanımlı |
| `qdrant` | 6333 (REST/dashboard), 6334 (gRPC) | `qdrant_storage` volume |
| `ollama` | 11434 | `ollama_models` volume; container'da CPU'da koşar |

**Veri ve model üretimi** (bir kez; sonuçlar `./data` ve `./artifacts`'a yazılır):

```bash
# A) Host'ta (GPU'lu makinede önerilir) — sıra yukarıdaki "Üretim komutları" gibidir
python scripts/download_dataset.py    # ham veri (yalnız ilk kez)
python scripts/02_normalize_smp.py
python scripts/tune_lgbm.py
python scripts/05_train_lgbm.py
python scripts/06_time_lift.py
python scripts/evaluate_final.py
python scripts/07_index_qdrant.py     # Qdrant'a yazar -> QDRANT_HOST'u host'a çevirin
python scripts/download_clip_model.py # medya analizi ağırlıkları (~600 MB, bir kez)

# B) Ya da tools profiliyle container içinde (tüm zinciri çalıştırır)
docker compose --profile tools run --rm trainer
```

**Hazır ağırlıklarla hızlı başlangıç (eğitim gerekmez):**

```bash
python scripts/sync_artifacts.py download   # ağırlıklar + parquet (yeniden başlatılabilir)
python scripts/07_index_qdrant.py           # (bir kez) Qdrant indeksini kur
docker compose up -d --build                # ya da yerel: uvicorn backend.app:app
```

İndirilenler: `artifacts/` (Katman A modeli, Katman B lift tablosu, metin SVD,
guardrail modeli, retrieval encoder'ı, metrikler, final değerlendirme) ve
`data/processed/posts.parquet`. Kimlik bilgileri `.env`'den (`WEBDAV_URL`,
`WEBDAV_USER`, `WEBDAV_PASSWORD`) veya ortam değişkeninden okunur.

Yeni ağırlık yayınlamak için (bakım):

```bash
python scripts/sync_artifacts.py upload     # güncel artifacts/ + parquet yüklenir
```

**Ortam değişkenleri**

Ayarların tek kaynağı kök dizindeki `.env` dosyasıdır: `backend/env_loader.py`
dosyayı süreç ortamına yükler, `backend/config.py`, `backend/logging_setup.py`
ve script'ler değerleri oradan okur. Şablon: `.env.example` (`cp .env.example .env`).

İki kural:

- **Süreç ortamı `.env`'i geçersiz kılar.** `docker compose`, CI ve
  `LOG_LEVEL=DEBUG uv run uvicorn backend.app:app` gibi tek seferlik
  özelleştirmeler aynen çalışmaya devam eder.
- **Her anahtarın kod içinde bir varsayılanı vardır.** `.env` olmadan da
  uygulama ayağa kalkar; dosya yalnızca varsayılanı değiştirmek için gereklidir.

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `API_PORT` | 8000 | API'nin host portu (yalnızca compose) |
| `GEMMA_API_URL` | `http://127.0.0.1:11434` | LLM uç noktası (compose içinde `ollama` servisi) |
| `GEMMA_MODEL_NAME` | `gemma4:e4b` | Ollama model kimliği (HuggingFace adı `google/gemma-4-E4B-it` registry'de yok) |
| `QDRANT_HOST` | otomatik keşif | Boşsa localhost → podman VM adresi denenir |
| `QDRANT_PORT` | 6333 | Qdrant REST portu |
| `LOG_LEVEL` | INFO | Uygulama log seviyesi |
| `CLIP_MODEL_NAME` | `openai/clip-vit-base-patch32` | Medya analizi modeli |
| `MEDIA_CACHE_DIR` | `<repo>/models/hf` | Ağırlık önbelleği (bind-mount edilir) |
| `MEDIA_DEVICE` | `cpu` | `cpu` \| `auto` \| `cuda` \| `directml` |
| `MAX_IMAGE_MB` / `MAX_VIDEO_MB` | 10 / 50 | Yükleme boyut sınırları |
| `MAX_VIDEO_SECONDS` | 60 | Video süre sınırı |
| `VIDEO_FRAME_COUNT` | 8 | Video başına örneklenen kare |
| `MEDIA_ANALYSIS_TTL_SECONDS` | 1800 | Medya analizi önbellek ömrü |
| `MEDIA_TOP_TAGS` | 3 | Gönderi başına etiket sayısı |
| `MEDIA_MIN_PROB` / `MEDIA_MIN_MARGIN` / `MEDIA_TAG_MIN_PROB` | 0.35 / 0.10 / 0.10 | CLIP güven eşikleri |
| `HF_HUB_OFFLINE` | `0` | Çevrimdışı demo için `1` |
| `SMPD_MEDIA_ROOT` | `data/raw/media` | `media_available` doğrulamasının kök dizini |
| `WEBDAV_URL` / `WEBDAV_USER` / `WEBDAV_PASSWORD` | — | Veri kümesi + ağırlık senkronu |
| `NSOSYAL_API_BASE_URL` / `NSOSYAL_API_TOKEN` / `NSOSYAL_PSEUDONYM_SALT` | — | Gerçek NSosyal ingest'i (yoksa adaptör hata verir) |

`docker compose` yalnızca container'a anlamlı olan anahtarları geçirir
(`GEMMA_MODEL_NAME`, `LOG_LEVEL`, `HF_HUB_OFFLINE`, `API_PORT`) ve ağ adreslerini
(`QDRANT_HOST=qdrant`, `GEMMA_API_URL=http://ollama:11434`) kendisi sabitler —
host'a göre yazılmış `.env` değerleri container içine sızmaz.

**Notlar**

- Bu makinede **8081–8280 portları Windows tarafından rezerve**; API için 8000
  gibi aralık dışı bir port kullanın (`WinError 10013` bind hatası verir).
- Podman'da yayınlanan portlar bu makinede host `localhost` yerine **podman VM
  IP'sinden** erişilebilir (örn. `http://172.17.78.187:8000`).
- Linux host'ta bind-mount edilen `./artifacts` container kullanıcısı
  (UID 10001) tarafından yazılabilir olmalı: `sudo chown -R 10001 ./artifacts`.

### Yerel (geliştirme)

```bash
uvicorn backend.app:app        # API (Qdrant/Ollama opsiyonel; yoksa fallback)
pytest tests/                  # test paketi
LOG_LEVEL=DEBUG uvicorn backend.app:app   # ayrıntılı loglar
python scripts/idea_battery.py --base-url http://127.0.0.1:8000  # canlı API bataryası
python scripts/train_guardrail_model.py   # guardrail modelini yeniden eğit
```

## Artefaktlar

| Dosya | İçerik |
|---|---|
| `artifacts/base_potential_lgbm.txt` | Katman A booster'ı (24 feature, zamansız) |
| `artifacts/base_potential_metrics.json` | Train/validation metrikleri, A0–A4 ablasyonları, provenance |
| `artifacts/time_lift_table.json` | Katman B lift tablosu + destek + CI + kanıt seviyeleri |
| `artifacts/final_evaluation.json` | Kilitli test raporu (B/C/D + legacy karşılaştırması) |
| `artifacts/text_svd_model.joblib` | Train-only TF-IDF + SVD |
| `artifacts/tuning_results.json` | Validation-only seçim kaydı (tüm adaylar) |
| `artifacts/legacy/` | Devir öncesi artifact'lar (runtime **yüklemez**) |

Her eğitim çıktısı veri hash'ini, git commit'ini, eğitim zamanını, satır
sayısını, split sınırlarını ve config'i taşır.

## Üçüncü taraf veriler

Bkz. `NOTICE.md` (SMPD, troff-v1.0, teamgzg, kelime listeleri ve lisansları).
