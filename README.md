# N-Pusula (EnPusula)

## Web arayüzü

Son Stitch tasarımlarına göre geliştirilen React/Vite uygulaması `frontend/` klasöründedir. Kurulum ve çalıştırma için [frontend/README.md](frontend/README.md) belgesine bakın. Arayüz varsayılan olarak mock modunda çalışır.

Arayüzün `/v1/pusula/*` sözleşmesi ile bu backend'in `/api/recommend/*` ve `/api/profile/*` uçları henüz eşlenmemiştir. HTTP modunu açmak tek başına entegrasyonu tamamlamaz; adaptör ve proxy yol eşlemesi uygulanmalıdır. Ayrıntılar: [entegrasyon belgesi](frontend/docs/backend-integration.md).

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
- `POST /api/media/analyze` — yüklenen fotoğraf/videoyu CLIP ile analiz eder
  (konu, kanonik kategori, etiketler); dönen `media_id` advisor isteğine
  eklenince görsel kanıt öneriye girer
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
| Medya analizi | `backend/services/media_analysis.py`, `models/` | CLIP ViT-B/32 zero-shot: konu, kanonik kategori, etiketler (video: 8 kare ortalaması) |
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
- Medya analizi yalnızca **yüklenen dosya** üzerinde çalışır; korpustaki
  görsellerle karşılaştırma yapılmaz (veri paketinde görsel dosyası yok).
  Etiketler küratörlü bir bankadan gelir ve yalnızca görsel olarak ayırt
  edilebilir kavramları içerir (#kahve, #fitness); finans veya girişimcilik
  gibi soyut konular görselden çıkarılmaz, Gemma yargıcına bırakılır.

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
| Etiketler | Görsel etiketleri listenin başına geçer; mevcut 3'lük sınır korunur |

Ölçülen süreler (CPU): görsel ~0.06 sn, 8 kareli video ~0.5 sn, model yükleme
~7 sn (açılışta bir kez).

**Eşik altındaysa "belirsiz" denir:** `topic` / `canonical_category` `null`
döner ve karar bir üst katmana bırakılır — argmax'ın sessizce ilk sınıfı
seçmesi HIKAYE.md Bölüm 9'da kayıtlı bir hataydı.

**Model feature sözleşmesi değişmez:** SMPD paketi medya dosyası dağıtmadığı
için (`flickr_smpd_dataset.md`) görsel feature'ı eğitim korpusuna eklenemez;
36 kolonluk sözleşme ve `artifacts/lgbm_popularity.txt` aynı kalır, yeniden
eğitim gerekmez. Görsel analizi mevcut girdileri besler: kategori kolonları
(doğrudan uygulanır) ve etiketler.

**Ağırlıklar yoksa:** `/api/media/analyze` 503 döner, `/api/health` içinde
`media_analyzer_ready: false` görünür; advisor metin-only çalışmaya devam eder
— yani demo medyaya bağımlı değildir.

**Not (GPU):** CLIP varsayılan olarak CPU'da koşar. `MEDIA_DEVICE=auto`
DirectML'i dener, ancak bu makinede torch-directml bu modeli çalıştıramıyor
(`Cannot set version_counter for inference tensor`) ve CPU'ya düşer; CPU
süreleri demo için fazlasıyla yeterlidir.

## Çalıştırma

### Docker Compose ile (önerilen / production)

Gereksinimler: Docker Desktop veya Podman + compose sağlayıcısı. Veri seti ve
model çıktıları container'a **bind-mount** edilir (`./data`, `./artifacts`);
ilk çalıştırmadan önce bir kez üretilmeleri gerekir (aşağıdaki "Veri ve model
üretimi" bölümü).

```bash
docker compose up -d --build     # qdrant + ollama (+ model indirme) + api
docker compose logs -f api       # uygulama logları (LOG_LEVEL ile seviye)
```

İlk açılışta `ollama-init` hizmeti `GEMMA_MODEL_NAME` modelini (varsayılan
`google/gemma-4-E4B-it`) otomatik indirir. İndirme tamamlanana kadar
LLM'e bağlı yollar (konu yargıcı, açıklama üretimi) deterministik
fallback'lerine düşer; API bu sırada da çalışır.

| Servis | Port | Not |
|---|---|---|
| `api` | 8000 (`API_PORT`) | `/api/health` healthcheck'i tanımlı |
| `qdrant` | 6333 (REST/dashboard), 6334 (gRPC) | `qdrant_storage` volume |
| `ollama` | 11434 | `ollama_models` volume; container'da CPU'da koşar |

**Veri ve model üretimi** (bir kez; sonuçlar `./data` ve `./artifacts`'a yazılır):

```bash
# A) Host'ta (GPU'lu makinede önerilir)
python scripts/download_dataset.py    # ham veri (yalnız ilk kez)
python scripts/02_normalize_smp.py
python scripts/07_index_qdrant.py     # Qdrant'a yazar -> QDRANT_HOST'u host'a çevirin
python scripts/05_train_lgbm.py
python scripts/download_clip_model.py # medya analizi ağırlıkları (~600 MB, bir kez)

# B) Ya da tools profiliyle container içinde (Qdrant'a compose ağından bağlanır)
docker compose --profile tools run --rm trainer
```

**Hazır ağırlıklarla hızlı başlangıç (eğitim gerekmez):**

Takım arkadaşları eğitilmiş ağırlıkları Nextcloud'dan doğrudan indirip
sıfırdan eğitim yapmadan çalıştırabilir (~73 MB; kesintide kaldığı yerden
devam eder, tamamlanmış dosyaları atlar):

```bash
python scripts/sync_artifacts.py download   # 7 dosya: ağırlıklar + parquet
python scripts/07_index_qdrant.py           # (bir kez) Qdrant indeksini kur
docker compose up -d --build                # ya da yerel: uvicorn backend.app:app
```

İndirilenler: `artifacts/` (LightGBM modeli, metin SVD, guardrail modeli,
retrieval encoder'ı, metrikler) ve `data/processed/posts.parquet`. Kimlik
bilgileri `.env`'den (`WEBDAV_URL`, `WEBDAV_USER`, `WEBDAV_PASSWORD`) veya
ortam değişkeninden okunur — `download_dataset.py` ile aynı sözleşme.

Yeni ağırlık yayınlamak için (bakım):

```bash
python scripts/sync_artifacts.py upload     # güncel artifacts/ + parquet yüklenir
```

**Ortam değişkenleri** (compose'da varsayılanlarıyla hazır):

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `API_PORT` | 8000 | API'nin host portu |
| `GEMMA_API_URL` | `http://ollama:11434` | LLM uç noktası |
| `GEMMA_MODEL_NAME` | `google/gemma-4-E4B-it` | Ollama model adı |
| `LOG_LEVEL` | INFO | Uygulama log seviyesi |
| `CLIP_MODEL_NAME` | `openai/clip-vit-base-patch32` | Medya analizi modeli |
| `MEDIA_CACHE_DIR` | `./models/hf` | Ağırlık önbelleği (bind-mount edilir) |
| `MEDIA_DEVICE` | `cpu` | `cpu` \| `auto` \| `cuda` \| `directml` (bkz. aşağıdaki not) |
| `MAX_IMAGE_MB` / `MAX_VIDEO_MB` | 10 / 50 | Yükleme boyut sınırları |
| `MAX_VIDEO_SECONDS` | 60 | Video süre sınırı |
| `HF_HUB_OFFLINE` | `0` | Çevrimdışı demo için `1` |

**Notlar**

- Bu makinede **8081–8280 portları Windows tarafından rezerve**; API için 8000
  gibi aralık dışı bir port kullanın (`WinError 10013` bind hatası verir).
- Podman'da yayınlanan portlar bu makinede host `localhost` yerine **podman VM
  IP'sinden** erişilebilir (örn. `http://172.17.78.187:8000`; Qdrant da aynı
  şekilde `172.17.78.187:6333`). Docker Desktop'ta `localhost` çalışır.
- GPU'lu Ollama'yı host'ta çalıştırmak isterseniz (Windows'ta DirectML ile daha
  hızlı): compose'daki `ollama`'yı kaldırıp `GEMMA_API_URL`'i host'a çevirin —
  Docker Desktop'ta `http://host.docker.internal:11434`, Podman'da
  `http://host.containers.internal:11434`.
- Linux host'ta bind-mount edilen `./artifacts` container kullanıcısı
  (UID 10001) tarafından yazılabilir olmalı: `sudo chown -R 10001 ./artifacts`.

### Yerel (geliştirme)

```bash
uvicorn backend.app:app        # API (Qdrant/Ollama opsiyonel; yoksa fallback)
pytest tests/                  # test paketi (66 test)
LOG_LEVEL=DEBUG uvicorn backend.app:app   # ayrıntılı loglar
python scripts/idea_battery.py --base-url http://127.0.0.1:8000  # canlı API bataryası
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
