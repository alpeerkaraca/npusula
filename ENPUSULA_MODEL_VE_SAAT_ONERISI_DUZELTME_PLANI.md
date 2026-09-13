# EnPusula — Model, Veri ve Saat Önerisi Düzeltme Planı

## Pull #1 sonrası güncelleme — 13 Eylül 2026

Bu plan, `e1c0e68` merge commit'i (PR #1) incelenerek güncellenmiştir. Aşağıdaki iyileştirmeler **zaten uygulanmış** durumdadır; agent bunları yeniden yazmamalı, regression test/provenance ile korumalıdır.

| Pull ile gelen değişiklik | Durum | Bu plan açısından anlamı |
|---|---|---|
| 55 sentetik demo postu veri setinden çıkarıldı | Uygulandı | Eğitim/test temizliği için ana düzeltme yapıldı; yeniden eğitimde veri sayısı 305.613 gerçek SMPD satırı olmalı |
| Demo odaklı testler gerçek SMPD kullanıcılarına geçirildi | Uygulandı | Demo fixture'a bağlı testleri geri getirme |
| Aday saatler 4 sabit saatten 7 × 24 = 168 saate çıkarıldı | Uygulandı | Saat kapsaması iyileşti; yine de final UX'te tek saat yerine belirsizlikli zaman penceresi gösterilecek |
| Kategori confidence sabit mock değerden match-density heuristic'ine geçirildi | Uygulandı | Bu değer hâlâ eğitilmiş model güveni değildir; açıklama ve test gerekir |
| Fotoğraf/video yükleme için CLIP ViT-B/32 analizi eklendi | Uygulandı | Yalnız inference'ta kategori/tag input'unu zenginleştirir; SMPD'de medya dosyası olmadığından mevcut 36-feature eğitimine image embedding eklenmiş değildir |
| Docker, artifact sync ve structured logging eklendi | Uygulandı | Yeniden eğitimde artifact provenance ve reproducibility için kullanılabilir; model metodolojisi sorunlarını tek başına çözmez |

Bu pull sonrasında kayıtlı M5 metriği yaklaşık `MAE=0.853`, `Spearman=0.870` olarak güncellenmiştir. Bu değer yine **post popularity tahmin metriğidir**, saat önerisi başarısı değildir.

## Amaç ve karar

Mevcut sistem teknik olarak çalışıyor; fakat kayıtlı `MAE≈0.853` ve `Spearman≈0.870` değerleri esas olarak **post popularity tahminini** ölçüyor. Bunlar, sistemin aynı içerik için “kesin en iyi saati” bulduğunu kanıtlamaz.

Bu planın amacı sistemi iki açık katmana ayırmaktır:

```text
Katman A — Post potansiyeli
“Bu içerik, bu hesabın mevcut geçmişiyle genel olarak ne kadar performans gösterebilir?”

Katman B — Zaman penceresi
“Bu kategori/içerik için hangi geniş paylaşım pencereleri gözlemsel olarak daha olumlu residual lift göstermiş?”
```

Ürün çıktısı bundan sonra “kesin en iyi saat” değil, kanıt seviyesiyle beraber **önerilen zaman aralığı** olacaktır.

```text
Doğru ürün dili:
“Teknoloji içeriği için Salı 18.00–21.00 aralığı desteklenen bir pencere.”

Yanlış ürün dili:
“Kesin en iyi saat Salı 18.00.”
```

Bu plan uygulanmadan eski `metrics.json` değerleri ürünün saat önerisi başarısı olarak sunulmayacaktır.

---

## Mevcut sorunların net teşhisi

| Konu | Mevcut durum | Neden sorun? |
|---|---|---|
| Hedef metrik | Post-level MAE/Spearman ölçülüyor | “Aynı içerikte en iyi slot” sıralamasını ölçmüyor |
| Slot kapsamı | Adaylar artık 7 × 24 = 168 saat | Kapsam düzeldi; ham saat skorları hâlâ belirsizliksiz sıralanıyor ve UI'da pencereye toplanmıyor |
| Slot farkları | Aday skorları çoğunlukla 0.03–0.10 farkta | Kesin saat sıralaması için kırılgan; belirsizlik gösterilmiyor |
| Veri türü | Flickr gözlemsel verisi | Saat etkisi nedensel/A-B testi kanıtı değildir |
| Test seti | Tuning ve quantile seçimi testte incelenmiş | Test artık dokunulmamış final değerlendirme değildir |
| Demo kayıtları | Pull #1 ile kaldırıldı | Yeniden normalizasyonda geri gelmemesi assertion ve provenance ile korunmalı |
| Timezone | `time_basis="local"` işaretlenebiliyor ama gerçek `local_hour` üretilmiyor | Yerel saat önerisi yanlış sunulabilir |
| Residual model | `account_baseline` hem offset hem M5 input’u | Genel popularity performansı hesap geçmişine aşırı yaslanıyor |
| Tag alignment | Canonical kategori isimleri ile tag-domain isimleri farklı | “Uyumlu tag” ölçümü güvenilir değil |
| Cold start | MAE yaklaşık 1.93, Spearman yaklaşık 0.37 | Yeni kullanıcıya kişiselleştirilmiş kesin öneri verilemez |
| Eski artifact | PyTorch GPU modeli repoda kalmış ama runtime kullanmıyor | Mimari ve sunum kafa karıştırıyor |
| Yüklenen medya | CLIP ile kategori/tag çıkarılıyor | Güzel inference iyileştirmesi; ancak SMPD medya dosyası olmadığından popularity modelinin görsel eğitim feature'ı değildir |

### Önemli teknik düzeltme

`history_x_hour`, kullanıcının o saatteki önceki başarı ortalaması değildir. Mevcut kodda yalnızca:

```python
history_x_hour = history_depth_code * 100 + hour
```

hesaplanır. Bu feature kullanıcının 18.00’de kaç kez paylaştığını ya da 18.00 performansını tutmaz. Yine de yeni tasarımda kaldırılacaktır; zaman katmanı daha açık, denetlenebilir ve kullanıcıya açıklanabilir olmalıdır.

---

## Hedef mimari

```text
Ham SMPD JSONL (yalnız gerçek kayıtlar)
  ↓ normalize + gerçek timezone dönüşümü
posts.parquet
  ↓ kronolojik train / validation / kilitli test
  ├── Katman A: base-potential model
  │     içerik + hesap geçmişi → genel popularity potansiyeli
  │
  └── Katman B: time-lift table
        kategori × weekday × 3-saatlik local bucket
        → base modelden kalan residual lift + belirsizlik
  ↓
Inference
  ├── Post potansiyeli
  ├── Desteklenen zaman pencereleri
  └── Güven / belirsizlik / cold-start uyarısı
```

Katman B, “saat başarının sebebidir” iddiasında bulunmaz. Yalnız şunu söyler:

```text
“Tarihsel gözlemlerde, yeterli örnek bulunan bu kategori-zaman penceresi
base potansiyele göre pozitif residual lift göstermiştir.”
```

---

# Faz 0 — Güvenli çalışma kuralları

## 0.1 Çalışma dalı ve mevcut artifact’lar

- Değişiklikler ayrı bir Git branch’inde yapılacak.
- Eski `artifacts/metrics.json`, `artifacts/lgbm_popularity.txt` ve tuning sonuçları silinmeyecek; `artifacts/legacy/` altına taşınacak veya açıkça `legacy` etiketiyle korunacak.
- Yeni artifact’lar eski dosya adlarının üzerine ancak yeni metrik raporu üretildikten ve kabul kontrolleri geçtikten sonra yazılacak.
- Her eğitim çıktısına veri hash’i, commit SHA, eğitim zamanı, satır sayısı, split tarihleri ve config eklenecek.

## 0.2 Ürün iddiası

Uygulama ve README’de aşağıdaki dil kullanılacak:

```text
“Önerilen paylaşım penceresi”
“Tarihsel sinyal / gözlemsel lift”
“Güven seviyesi”
```

Şimdilik aşağıdaki ifadeler kaldırılacak:

```text
“Kesin en iyi saat”
“Bu saatte mutlaka daha fazla etkileşim alırsın”
“Nedensel olarak en iyi zaman”
```

---

# Faz 1 — Veri hattını temizle ve gerçek yerel zamanı üret

## 1.1 Demo kayıtlarını eğitim verisinden kesin ayrı tut — Pull #1 ile uygulanmış, şimdi koru

### Değişecek dosya

`scripts/02_normalize_smp.py`

### Yapılacaklar

Pull #1 normalizer'daki demo birleştirme bloğunu kaldırmıştır. Agent'ın görevi bunu tekrar uygulamak değil, aşağıdaki korumaları eklemek ve yeniden eğitimde doğrulamaktır:

1. Normalizer yalnız `data/raw/train_dataset.jsonl` içindeki gerçek SMPD satırlarını yazacak.
2. `posts.parquet` hiçbir koşulda önceki output'tan demo satırı okumayacak/eklemeyecek.
3. Demo kullanıcı postları varsa yalnız ayrı demo kaynağında kalacak; eğitim, tuning, final test ve Qdrant training index'ine girmeyecek.
4. Normalizer sonunda aşağıdaki assertion eklenecek:

```python
assert (df["source"] == "smpd_real").all()
assert not df["user_id"].isin(DEMO_USER_IDS).any()
assert len(df) == expected_raw_valid_row_count
```

5. Data quality report’a `source_counts`, `demo_row_count`, `raw_file_sha256` eklenecek.

### Kabul kriteri

```text
dataset_rows = gerçek geçerli SMPD satır sayısı
demo_row_count = 0
source_counts = {"smpd_real": dataset_rows}
```

## 1.2 Gerçek local zaman feature’ı üret

### Değişecek dosyalar

- `scripts/02_normalize_smp.py`
- `backend/services/recommendation.py`
- `backend/services/candidate_generator.py`
- API request schema’ları

### Yapılacaklar

1. `published_at_utc` parse edilip gerçekten UTC timestamp olarak saklanacak.
2. `timezone_offset` mevcutsa, postun local zamanı bu offset ile hesaplanacak:

```text
local_datetime
local_hour
local_weekday
timezone_basis = "source_offset"
```

3. Offset yoksa:

```text
local_hour = UTC hour
local_weekday = UTC weekday
timezone_basis = "utc_fallback"
```

4. Eğitimde saat ve weekday yalnız `local_hour` / `local_weekday` üzerinden üretilecek.
5. Inference isteğine kullanıcının IANA timezone’u veya offset’i eklenecek. Aday slotlar önce kullanıcının local zamanında üretilecek, sonra gerektiğinde UTC’ye dönüştürülecek.
6. Offset bilinmiyorsa UI/API güveni düşürecek ve UTC fallback açıkça işaretlenecek.

### Kabul kriterleri

- `+03:00` kaynak postu için UTC 18.00 → local 21.00 test edilir.
- Kullanıcının response’unda görünen zaman local zamanla aynı olur.
- `time_basis="local"` etiketi yalnız gerçek dönüşüm yapıldıysa kullanılabilir.

## 1.3 Veri sözleşmesini düzelt

### Yapılacaklar

- `PostRecord` Pydantic şeması ile normalizer output kolonları hizalanacak.
- Normalizer, schema’yı yalnız dokümante etmek yerine sample/batch validation ile kullanacak.
- `media_available=True` yalnız dosyanın gerçekten erişilebilir olduğu doğrulanırsa verilecek; kaynak statüsü tek başına yeterli sayılmayacak.
- Bilinmeyen medya türü `photo`ya çevrilmeyecek; `unknown` olarak saklanacak.
- `source_user_photo_count` saklanabilir fakat eğitim feature setine alınmayacağı test ile güvence altına alınacak.

### Pull #1 medya analiziyle uyum kuralı

CLIP media analysis ayrı bir inference servisi olarak korunacak. Şu anki veri gerçeği:

```text
SMPD training corpus → medya dosyaları yok → CLIP embedding ile popularity eğitimi yok
Kullanıcının yüklediği medya → CLIP category/tag hint'i → mevcut advisor input'larını iyileştirir
```

Bu nedenle agent, CLIP'in 512-D embedding'ini mevcut LightGBM eğitimine “varmış gibi” eklemeyecek. Görsel popularity feature'ı ancak EnSosyal veya lisanslı, dosyası mevcut eğitim korpusu geldiğinde ayrı veri sözleşmesi ve yeniden eğitimle eklenebilir.

---

# Faz 2 — Değerlendirme protokolünü temizle

## 2.1 Dokunulmamış final test seti oluştur

### Değişecek dosyalar

- `scripts/05_train_lgbm.py`
- `scripts/tune_lgbm.py`
- yeni: `scripts/evaluate_final.py`

### Yeni kural

```text
Train (%70): model parametrelerini öğrenir.
Validation (%15): hyperparameter, objective, alpha, bucket boyutu ve confidence eşikleri seçilir.
Test (%15): yalnız tek final run’da okunur; tuning veya karar için kullanılmaz.
```

### Yapılacaklar

1. `tune_lgbm.py` test split’i hiç yüklemeyecek; yalnız validation’a göre config seçecek.
2. Quantile alpha tercihi validation pinball loss, validation tail metrics ve ürün hedefiyle yapılacak.
3. Seçim kilitlendikten sonra `evaluate_final.py` tek defa çalışacak.
4. Test sonucu metadata’sında `test_touched_before_final=false` alanı bulunacak.
5. Eğer eski test seti zaten tuning için kullanıldıysa yeni bir zaman bloklu holdout ayrılacak veya eski test açıkça `development_test` diye yeniden adlandırılacak.

### Kabul kriteri

Final raporunda açıkça şu alanlar yer alır:

```json
{
  "split_protocol": "chronological_train_validation_locked_test",
  "tuning_data": "validation_only",
  "test_touched_before_final": false,
  "dataset_sha256": "...",
  "git_commit": "..."
}
```

## 2.2 Leakage testlerini genişlet

### Yapılacaklar

- Mevcut expanding-window history testi korunacak.
- Aynı kullanıcının gelecekteki yüksek popularity postu eklenince geçmiş satır feature’larının değişmediğini test et.
- Mevcut postun `popularity_score` değeri değiştirilince yalnız sonraki aynı-user postlarının prior’ının değiştiğini test et.
- Global/category medyanlarının yalnız train bölmesinden üretildiğini test et.
- Text TF-IDF vocabulary’sinin validation/test başlıklarına fit edilmediğini test et.

---

# Faz 3 — Feature sözleşmesini sadeleştir ve tag/category uyumunu düzelt

## 3.1 Ortak canonical category sözleşmesi

### Değişecek dosyalar

- `backend/services/canonical_taxonomy.py`
- `backend/services/tag_taxonomy.py`

### Yapılacaklar

1. Post canonical kategorileri ve tag-domain kategorileri için tek bir enum/sözlük tanımla.
2. Örnek eşlemeler açıkça yazılsın:

```text
technology       ↔ tech_software
fashion_beauty   ↔ beauty_cosmetics + fashion_apparel
social_lifestyle ↔ social_events
art_design       ↔ art_entertainment + urban_architecture
```

3. `align_tags` yalnız “tag sözlükte var mı?” demesin; sonucu aşağıdaki sınıflarda döndürsün:

```text
aligned_semantic
mismatched_semantic
generic_promotional
nsfw_filtered
unknown
```

4. Bilinmeyen tag otomatik olarak “anlamsız” ilan edilmesin; ayrı `unknown_tag_count` olarak tutulmalı.
5. Title + SMPD taxonomy ile kategori belirlenirken fallback, confidence ve secondary category açıkça test edilmeli.

## 3.2 Base model feature setini ürün amacına göre ayır

### Yeni feature grupları

```text
Base-potential features:
- account_baseline: deterministic offset olarak kullanılır
- history_depth_code
- canonical category/subcategory
- context source/confidence
- temizlenmiş tag özetleri
- media_type
- title SVD/text features

Base modelden çıkarılacaklar:
- hour
- weekday
- month
- hour_sin/hour_cos
- weekday_sin/weekday_cos
- cat_x_hour
- cat_x_weekday
- history_x_hour
```

### Karar

Base model residual eğitilecekse `account_baseline` hedefin offset’i olacak, fakat aynı anda model input’u olmayacak.

```text
residual_target = popularity_score - account_baseline
base_residual_model input = içerik + history_depth + tag + media + text
final_base_prediction = account_baseline + predicted_residual
```

Bu tasarımın amacı account baseline’ı tamamen atmak değil; onun modeli ezip geçmesini engelleyip işlevini açıkça “hesap seviyesi offset’i” olarak sınırlamaktır.

### Gerekli ablation’lar

| Deney | Amaç |
|---|---|
| A0: global/category baseline | Alt sınır |
| A1: account offset only | Hesap geçmişinin katkısı |
| A2: account offset + content | İçerik/tag/metnin katkısı |
| A3: A2 + media | Medya türü katkısı |
| A4: eski M5 | Legacy karşılaştırması; üretim adayı değildir |

Her deney overall, cold-start, very-low-history ve kategori bazında raporlanacak.

---

# Faz 4 — Ayrı ve açıklanabilir zaman-lift katmanı

## 4.1 Bucket tasarımı

Pull #1 ile aday üreticisi artık 7 gün × 24 saat = 168 aday üretiyor. Bu kapsam korunabilir; fakat bu 168 ham skor kullanıcıya ayrı ayrı “kesin sıralama” olarak gösterilmeyecek. Katman B, saatlik adayları aynı 3 saatlik **local time bucket** altında toplayacak ve tek bir gözlemsel lift/evidence kararı verecek.

Saatler dakika dakika veya tek tek ürün iddiası olarak yarışmayacak. İlk sürümde 3 saatlik local bucket kullanılacak:

```text
00–03, 03–06, 06–09, 09–12,
12–15, 15–18, 18–21, 21–24
```

Gerekirse validation verisinde 4 saatlik bucket alternatifi denenir; seçim testten önce kilitlenir. 168 aday taraması yalnız bucket sınırlarının gelecekteki takvimdeki somut zamanlarını üretmek için kullanılabilir.

## 4.2 Time lift nasıl hesaplanacak?

Katman A train postlar için out-of-fold / chronologically valid base prediction üretir.

Her post için:

\[
base\_residual_i = y_i - \hat y^{base}_i
\]

Sonra şu gruplar için residual ortalaması hesaplanır:

```text
canonical_category × local_weekday × local_time_bucket
```

Örnek:

```text
technology × Tuesday × 18–21
```

Bu değere doğrudan güvenmek yerine global sıfıra doğru shrinkage uygulanır:

\[
lift_{group} = \frac{n \cdot meanResidual_{group} + k \cdot 0}{n + k}
\]

Burada `k` validation’da seçilen smoothing kuvvetidir.

Az örnekli gruplar otomatik olarak daha nötr lift’e yaklaşır.

## 4.3 Hiyerarşik fallback

Bir grup yeterli veri içermiyorsa aşağıdaki sırayla genişlet:

```text
category × weekday × bucket
  ↓
category × bucket
  ↓
global weekday × bucket
  ↓
global bucket
  ↓
no time claim / neutral lift
```

Her önerinin yanında hangi seviyenin kullanıldığı artifact/API alanı olarak dönecek:

```text
evidence_level = category_weekday_bucket | category_bucket | global_bucket | neutral
```

## 4.4 Belirsizlik ve confidence

Her lift için en az aşağıdakiler tutulacak:

```text
support_post_count
support_user_count
mean_lift
bootstrap_ci_low
bootstrap_ci_high
evidence_level
```

Bootstrap kullanıcı bazında yapılmalı; aynı kullanıcının postları bağımsız kabul edilmemeli.

### UI/API karar kuralı

Kesin sıralama ancak aşağıdakiler sağlanırsa gösterilir:

1. En iyi bucket’ın yeterli support’u vardır.
2. En iyi bucket’ın bootstrap CI’ı nötrden güvenilir biçimde ayrılır.
3. Birinci ve alternatif bucket arasındaki fark validation’da seçilmiş minimum meaningful lift eşiğini geçer.

Aksi durumda:

```text
“Bu içerik için saat etkisi belirgin değil.
18.00–21.00 veya 21.00–24.00 aralığından uygun olanı seçebilirsin.”
```

Gösterilecek dil:

```text
Güven yüksek: yeterli örnek + net pozitif lift
Güven orta: yeterli örnek ama fark küçük
Güven düşük: cold start, UTC fallback, az örnek veya lift belirsiz
```

## 4.5 Inference akışı

```text
Yeni fikir + kullanıcı + local timezone
  ↓
canonical category / text / tag features
  ↓
Katman A: base potential
  ↓
Katman B: her 3 saatlik bucket için lift + belirsizlik
  ↓
base potential + time lift
  ↓
Tie-aware sıralama veya önerilen pencere
```

Bu katman kullanıcı bazlı “geçmişte hep bu saatte paylaştı” metriği kullanmayacak. EnSosyal verisi biriktikten sonra ayrıca kişiselleştirilmiş `user × category × bucket` katmanı eklenebilir; fakat minimum support ve shrinkage olmadan eklenmeyecek.

---

# Faz 5 — Yeniden eğitim ve metrik raporu

## 5.1 Yeniden üretim komutları

Agent, proje bağımlılıkları kurulduktan sonra sırasıyla çalıştıracak:

```text
1. Normalize gerçek SMPD verisi
2. Dataset quality / provenance report
3. Train-only vocabulary ve base-potential ablation eğitimleri
4. Validation-only tuning
5. Train/validation seçimi kilitlendikten sonra tek final test değerlendirmesi
6. Qdrant index'i yalnız retrieval için yeniden üret
7. API smoke test + test suite
```

Komutlar proje dokümantasyonunda gerçekten çalıştırılabilir biçimde güncellenecek; çıktı dosyaları ve config path’leri açıkça yazılacak.

## 5.2 Zorunlu yeni metrikler

### A. Veri/provenance

```text
raw row count
valid row count
unique users
date range
demo rows = 0
dataset hash
Git commit
split boundaries
timezone basis distribution
```

### B. Base-potential model

```text
MAE
Median AE
Spearman
L1 pinball loss veya quantile pinball loss (seçilen objective'e uygun)
Tail MAE ve tail bias
Calibration / prediction bias
```

Alt gruplar:

```text
cold start
very-low history
high history
timezone local / UTC fallback
her canonical kategori
photo / video
```

### C. Time-lift katmanı

Bu metrikler “nedensel en iyi saat” değil, held-out gözlemsel genelleme metrikleri olarak isimlendirilecek.

```text
supported bucket count
bucket support dağılımı
held-out bucket-lift MAE
held-out bucket-lift Spearman
top-1 / top-3 observed-lift hit rate (yalnız yeterli supportlu gruplar)
NDCG@3 (bucket sıralaması için)
mean ranking regret
positive-lift precision by confidence level
bootstrap CI coverage
tie / no-claim rate
```

### D. Ürün güven raporu

```text
high / medium / low confidence oranı
cold-start recommendation oranı
UTC fallback recommendation oranı
no-claim / broad-window fallback oranı
```

## 5.3 Metrik yorum kuralları

- `MAE` yalnız popularity tahmin başarısı olarak yazılacak.
- `Spearman` yalnız post popularity sıralama başarısı olarak yazılacak.
- Saat önerisi için `NDCG@3`, held-out lift ve confidence coverage ayrıca raporlanacak.
- Offline Flickr sonuçları “gözlemsel” etiketi taşır.
- EnSosyal A/B veya kontrollü exploration olmadan nedensel saat etkisi iddia edilmez.

---

# Faz 6 — API, UX, artifact ve test değişiklikleri

## 6.1 API response sözleşmesi

### Değişecek alanlar

Eski anlayış:

```text
datetime + kesin rank + relative potential
```

Yeni anlayış:

```json
{
  "window_start_local": "2026-...T18:00:00+03:00",
  "window_end_local": "2026-...T21:00:00+03:00",
  "weekday": "Salı",
  "base_potential": 7.1,
  "observational_time_lift": 0.12,
  "confidence": "medium",
  "support_post_count": 1240,
  "evidence_level": "category_weekday_bucket",
  "is_tie_or_broad_window": false,
  "timezone_basis": "user_timezone"
}
```

`relative_potential` kalacaksa şu anlama geldiği açıkça belirtilir:

```text
“Aday pencereler arasında modelin gözlemsel göreli skoru.”
```

Bu alan yüzde cinsinden kesin engagement artışı diye sunulmayacak.

## 6.2 Gemma açıklaması

Gemma prompt’una zorunlu kurallar eklenir:

- Kesin nedensel iddia kurma.
- Güven düşükse açıkça söyle.
- “Geçmiş gözlemlerde desteklenen pencere” dilini kullan.
- UTC fallback varsa kullanıcıya belirt.
- Tag önerisini ancak aligned semantic taglerden üret; belirsiz tagleri güvenle önermesin.

## 6.3 Eski GPU/PyTorch temizliği

- Runtime’da kullanılmayan `pytorch_popularity_gpu.pt` artifact’ı legacy arşive taşınacak veya kaldırılacak.
- Advisor yorumundaki “GPU Tabular NN + LightGBM ensemble” ifadesi düzeltilecek.
- README yalnız gerçekten çalışan runtime mimarisini anlatacak.

## 6.4 Testler

En az şu testler eklenecek:

```text
Demo satırının normalized train datasetine girememesi
UTC → local hour/weekday dönüşümü
Timezone bilinmeyince doğru fallback ve düşük confidence
Current post target'ının own prior'a girmemesi
Future same-user postun geçmiş feature'ı değiştirmemesi
Train-only text vocabulary
Train-only category medians
Tag canonical mapping: technology ↔ tech_software vb.
Mismatched tagin aligned sayılmaması
Base modelde time feature olmaması
Time-lift table'ın yalnız train/OOF residual kullanması
Az örnekli bucket'ın global sıfıra shrink olması
Belirsiz slotlarda broad-window / no-claim response
Cold-start response'un düşük confidence dönmesi
API response'ta local zamanın doğru görünmesi
```

---

# Faz 7 — EnSosyal geldiğinde gerçek adaptasyon

Flickr modeli yalnız başlangıç/benchmark rolünde kalacak. EnSosyal API ile gerçek loglar geldiğinde ayrı bir adaptasyon yapılacak.

## Toplanacak minimum veri

```text
post_id
user_id
published_at_utc
user timezone
canonical category
caption/title
tagler
media type
görsel/video context feature'ları (varsa)
impression/view count
like/comment/share/save
ölçüm penceresi: ör. 24 saat, 7 gün veya 30 gün
follower count (varsa; time-stamped)
```

## Önerilen öğrenme stratejisi

1. Önce aynı canonical feature sözleşmesine normalize et.
2. İlk aşamada Flickr modelini yalnız prior/başlangıç olarak kullan.
3. Kontrollü exploration yap:

```text
Kullanıcıya uygun 2–3 zaman penceresi sun.
Uygun pencereler arasında küçük, rastgeleleştirilmiş dağıtım uygula.
```

4. Hangi pencerenin gerçekten daha iyi olduğunu EnSosyal outcome’larından öğren.
5. Yeterli veri oluşunca contextual bandit veya platforma özel time-lift modeli değerlendir.

Rastgeleleştirme olmadan EnSosyal verisi de gözlemsel bias taşır; yalnız daha uygun domain verisi olur.

---

# Agent için uygulanma sırası

1. Mevcut kodu ve testleri envanterle; çalışma branch’i aç.
2. Faz 1 veri temizliği + timezone düzeltmesi + testleri uygula.
3. Normalized dataset’i yeniden üret; demo sayısının sıfır olduğunu doğrula.
4. Faz 2 split/tuning protokolünü uygula; eski test setinin statüsünü açıkça raporla.
5. Faz 3 taxonomy/tag sözleşmesini uygula ve feature contract’ı base/time diye ayır.
6. Faz 4 time-lift artifact ve uncertainty katmanını uygula.
7. Faz 5 ile tamamen yeniden eğitim yap; yeni metrik raporunu üret.
8. Faz 6 API/UX/README/artifact temizliğini uygula.
9. Tüm testleri çalıştır; veri olmadığı için çalıştırılamayan testleri açıkça raporla.
10. Son raporda eski ve yeni modelin metriklerini aynı veri/split protokolü altında karşılaştır.

## Bitirme kabul listesi

- [ ] Eğitim verisinde demo satırı yok.
- [ ] Yerel saat gerçekten hesaplanıyor ve inference local timezone ile çalışıyor.
- [ ] Test seti tuning için kullanılmıyor.
- [ ] Base-potential model ile time-lift katmanı ayrı artifact’lar.
- [ ] `history_x_hour`, `cat_x_hour`, `cat_x_weekday` üretim time modelinden kaldırıldı.
- [ ] Tag/category canonical mapping testlerle doğrulandı.
- [ ] Saatler geniş bucket/pencere olarak dönüyor.
- [ ] Yeterli kanıt yoksa sistem kesin rank yerine broad-window/no-claim dönüyor.
- [ ] Base popularity, cold-start, kategori ve time-lift metrikleri ayrı raporlanıyor.
- [ ] README ürünün gözlemsel sınırlarını ve gerçek çalışma mimarisini doğru anlatıyor.
- [ ] Eski GPU ensemble iddiası kaldırıldı.
