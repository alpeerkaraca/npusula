# NSosyal verisi geldiğinde adaptasyon planı (Faz 7)

Bu belge, bugünkü sistemin **ne olduğunu** ve NSosyal logları geldiğinde
**neyin değişeceğini** ayırır. Bugünkü Flickr/SMPD modeli bir *benchmark ve
başlangıç prior'udur*; ürünün kalıcı modeli değildir.

## Bugünkü durum (dürüst özet)

- Katman A ve Katman B, SMPD-Image (Flickr) üzerinde eğitildi. Bu korpus
  **gözlemseldir**: paylaşım saatleri rastgeleleştirilmemiştir, dolayısıyla
  saat ile etkileşim arasındaki ilişki karıştırıcı değişkenler içerir
  (hesap türü, bölge, içerik türü, mevsim).
- Kilitli test penceresinde Katman B'nin sıralama kalitesi şansa yakındır
  (NDCG@3 0.33; önerilen pencere − destekli pencere taban çizgisi +0.004) ve
  sistem bu yüzden vakaların %99.5'inde kesin sıralama yerine geniş pencere
  döndürür (`artifacts/final_evaluation.json`).
- Bu, "model bozuk" demek değildir; **bu korpusun bu soruyu cevaplamaya
  yetmediğinin ölçülmüş halidir.** Ürün dili de buna göre kurulmuştur.

## Toplanacak minimum veri

Bir satır = bir post. Aşağıdaki alanlar **zorunlu** (yoksa katmanlar yeniden
eğitilemez):

| Alan | Neden |
|---|---|
| `post_id`, `user_id` | aynı kullanıcının postlarını bağımsız saymamak için (kümeleme) |
| `published_at_utc` | kronolojik split ve OOF |
| `user_timezone` (IANA) | **kritik:** yerel saat olmadan pencere önerisi anlamsız |
| `canonical_category` | Katman B'nin grup anahtarı |
| `caption`/`title`, `tags`, `media_type` | Katman A içerik feature'ları |
| `impression`/`view` | popularity ölçeğinin paydası |
| `like`, `comment`, `share`, `save` | hedef değişken |
| ölçüm penceresi (24s / 7g / 30g) | hedeflerin karşılaştırılabilirliği |
| `follower_count` (zaman damgalı) | hesap büyüklüğü offset'i |

Opsiyonel ama yüksek değerli:

- görsel/video için dosya erişimi (varsa CLIP embedding'i **ancak o zaman**
  eğitime girebilir — bkz. "Yapılmayacaklar"),
- gösterim kaynağı (feed / keşfet / takipçi) — dağıtım karıştırıcısını
  kontrol etmenin tek yolu,
- ölçüm penceresi başına kümülatif eğriler (24s / 7g / 30g ayrı hedefler).

## Önerilen öğrenme stratejisi

1. **Aynı canonical sözleşmeye normalize et.** NSosyal satırları
   `PostRecord` şemasına (bkz. `backend/schemas/post.py`) ve
   `scripts/02_normalize_smp.py`'deki yerel zaman kurallarına uysun:
   `local_datetime` / `local_hour` / `local_weekday` + `timezone_basis`.
   Saat dilimi bilinmiyorsa satır `utc_fallback` olarak işaretlenir ve o
   satırlar Katman B'de **kullanılmaz**.
2. **Flickr modelini yalnız prior olarak kullan.** Katman A'yı NSosyal
   verisiyle yeniden eğitirken ilk sürümde Flickr modelinin çıktısını offset
   olarak korumak meşrudur; ama Katman B tablosu **sıfırdan** kurulur, çünkü
   platform, kitle ve etkileşim ölçeği farklıdır.
3. **Kontrollü keşif yap.** Kullanıcıya uygun **2–3 zaman penceresi** sun ve
   bu pencereler arasında küçük, rastgeleleştirilmiş bir dağıtım uygula
   (örn. %70/15/15). Öneri kalitesi düşmesin diye keşif payı, mevcut modelin
   en iyi penceresini dışlamayacak şekilde sınırlanır.
4. **Hangi pencerenin gerçekten daha iyi olduğunu outcome'lardan öğren.**
   Rastgeleleştirme olmadan NSosyal verisi de gözlemseldir; yalnızca
   daha uygun bir domain olur, nedensel kanıt olmaz.
5. **Yeterli veri birikince** contextual bandit veya platforma özel bir
   time-lift modeli değerlendir. Minimum destek ve shrinkage olmadan
   kişiselleştirilmiş `user × kategori × bucket` katmanı **eklenmez**.

## Yeniden eğitimde değişmeyen sözleşmeler

- İki katman ayrımı: zaman feature'ları Katman A'ya girmez.
- `account_baseline` offset'tir, model girdisi değildir.
- Kronolojik train/validation/kilitli test; tuning yalnız validation'da,
  test tek okuma (`scripts/evaluate_final.py`).
- Tag hizası sınıfları: aligned / mismatched / generic / NSFW / unknown.
- Öneri çıktısı **pencere**dir; kanıt seviyesi ve destek her zaman döner.
- Güven kuralı aynıdır: destek + CI sıfırdan ayrılması + anlamlı fark eşiği.
  Eşikler NSosyal validation'ında yeniden seçilir (`scripts/tune_lgbm.py`).

## Yapılmayacaklar

- **Rastgeleleştirme olmadan nedensel iddia yok.** "Bu saatte paylaşırsan
  etkileşim artar" cümlesi ancak A/B veya kontrollü keşif sonrası kurulur.
- **Dosyası olmayan görsel embedding eğitime katılmaz.** CLIP embedding'i
  ancak görsel/video dosyaları gerçekten mevcut olan bir korpusta, ayrı bir
  veri sözleşmesi ve yeniden eğitimle girer.
- **Kullanıcı davranışını zaman modeli sanmak yok.** "Kullanıcı hep 21.00'de
  paylaşıyor" bir tercih/bölge göstergesidir, o saatin daha iyi olduğunun
  kanıtı değildir.
- **Follower sayısını içerik feature'ı yapmak yok.** Hesap büyüklüğü offset
  tarafında (hesap geçmişi) temsil edilir; içerik modelinin içine sızmaz.
- **Küçük gruplara kesin sıralama yok.** Support altındaki gruplar hiyerarşide
  yukarı taşınır ve `evidence_level` bunu açıkça söyler.

## Sözleşme analizi: `nsosyal_features.json.shema` (keşfet akışı)

NSosyal'in paylaştığı şema Mastodon uyumlu bir status objesi. Adapter artık bu
sözleşmeye göre yazıldı ve testler bu şemaya birebir uyan sentetik fixture'la
koşuyor (`tests/fixtures/nsosyal/explore_feed_sample.json`).

| Sözleşme | Adapter davranışı |
|---|---|
| `{success, message, data:{items, total}}` | `unwrap_envelope` zarfı açar; `success:false` → açık hata (sessiz boş ingest yok) |
| `id`, `created_at`, `text`, `visibility`, `media_attachments[]`, `tags[{name}]` | kanonik kolonlara maplenir |
| `account.account_id` | `user_id` (tuzlu pseudonim) — hesabın diğer alanları satıra **girmez** |
| `favourites_count`, `replies_count`, `reblogs_count`, `quote_count`, `bookmarks_count` | like / comment / share (+quote) / save ağırlıkları |
| `views_count` | hedefin erişim metriği: `log1p(views_count)` |
| `detail_views_count`, `profile_views_count` | **kullanılmaz**: sayfa görüntülemesi, post dağıtımı değil |
| `visibility: private/direct` | varsayılan olarak **atlanır** ve sayılır (`allowed_visibility`) |
| `sensitive: true` | varsayılan olarak **atlanır** ve sayılır (`include_sensitive`) |
| `media_attachments[].type` | `image→photo`, `video/gifv→video`, `audio→unknown` (fotoğrafa çevrilmez) |
| `mentions`, `card`, `account.{username,display_name,bio,fields,avatar,header}`, `spoiler_text` | kişisel veri: satıra girmez, ingest raporunda "görüldü ve düşürüldü" olarak sayılır |

### ⚠️ Tek kritik eksik: zaman dilimi

Şemada **hiçbir yerde** timezone alanı yok — ne `Post` ne `Account` içinde.
Tek sinyal `created_at`:

| `created_at` | Sonuç |
|---|---|
| `"2026-09-12T21:30:00+03:00"` | gerçek yerel saat, `timezone_basis="source_offset"` |
| `"2026-09-12T18:30:00Z"` veya offsetsiz | yerel saat **bilinmiyor**, `timezone_basis="utc_fallback"` |

Fallback satırlar Katman A'yı eğitir ama **Katman B (pencere katmanı) onlar için
yerel saat iddiası kuramaz** — boru hattı bunu zaten zorunlu kılıyor. Yani
NSosyal `created_at`'i UTC gönderiyorsa, pencere önerisi tüm satırlarda
"belirsiz" kalır. NSosyal'den istenmesi gereken tek şey:

```text
Kullanıcının zaman dilimi (IANA adı veya UTC offset), post başına.
```

Bu alan gelmeden timing özelliği ölçülebilir hale gelemez; alan geldiğinde
`FIELD_CANDIDATES`'e iki satır eklenir ve zincir yeniden koşar.

## Adapter hazır: `backend/adapters/nsosyal.py`

NSosyal ekibinin entegrasyon için ihtiyaç duyacağı katman yazıldı. Adapter bir
**veri kabul sözleşmesidir**, veri toplama aracı değildir:

| Yapar | Yapmaz |
|---|---|
| Gelen payload'ı kanonik `PostRecord` kolonlarına mapler (alan adları `FIELD_CANDIDATES` içinde tek yerde) | Çerez/oturum yeniden kullanmaz, dokümante edilmemiş endpoint varsaymaz |
| `timezone_offset`/IANA ile yerel saati üretir (`local_hour`, `local_weekday`, `timezone_basis`) | Kullanıcı adı, profil metni, konum saklamaz |
| KVKK süzgeci: `user_id` tuzlu hash ile pseudonimize, metinden URL/@handle/e-posta/telefon temizliği | Medya dosyası indirmez (yalnız yerel ayna varsa `media_available=True`) |
| Hedef değişkeni tek bir belgeli formülle üretir (`log1p(views)`, yoksa `log1p(ağırlıklı etkileşim)`) | Etkileşim yoksa satır uydurmaz — payload'ı atlar ve sayar |
| Batch'i aynı kapılardan geçirir (kolon sözleşmesi + `PostRecord` örnek doğrulaması + leakage-free prior'lar) | Kategori uydurmaz: kanonik olmayan platform etiketi boş bırakılır, sınıflandırıcı devralır |

Transport **yetkili** olmak zorundadır: `NSOSYAL_API_BASE_URL` + `NSOSYAL_API_TOKEN`
(NSosyal'in verdiği kimlik) yoksa `fetch_posts` hata verir. Pseudonimizasyon için
`NSOSYAL_PSEUDONYM_SALT` zorunludur (yoksa hata verir; tahmin edilebilir tuz
pseudonimi geri döndürülebilir yapar).

Testler: `tests/test_nsosyal_adapter.py` (sentetik fixture'larla; repoda hiçbir
gerçek NSosyal verisi yoktur).

### Entegrasyon sırası

1. NSosyal `NSOSYAL_API_BASE_URL` + token + veri işleme sözleşmesini sağlar.
2. `FIELD_CANDIDATES` gerçek sözleşmeye göre güncellenir (tek dosya, tek tablo).
3. `ingest_payloads` ile çekilen batch `posts.parquet`'e yazılır
   (`source="nsosyal"`, aynı kolonlar).
4. `tune_lgbm.py → 05_train_lgbm.py → 06_time_lift.py → evaluate_final.py`
   zinciri NSosyal verisiyle yeniden koşar.

## Uygulama sırası (NSosyal verisi elde edildiğinde)

1. Yeni kaynağı `scripts/02_normalize_smp.py`'ye kardeş bir normalizer olarak
   ekle (aynı `PostRecord` sözleşmesi, `source="nsosyal"`, demo kapıları).
2. `data_quality.json` eşdeğerini üret: satır sayısı, kullanıcı sayısı, tarih
   aralığı, `timezone_basis` dağılımı, ölçüm penceresi dağılımı.
3. `scripts/tune_lgbm.py` → yeni validation'da eşikleri ve bucket boyutunu
   yeniden seç.
4. `scripts/05_train_lgbm.py` → Katman A'yı yeniden eğit (Flickr modelini
   `--init-model` benzeri bir offset olarak kullanmak opsiyonel).
5. `scripts/06_time_lift.py` → Katman B tablosunu **sıfırdan** kur.
6. `scripts/evaluate_final.py` → kilitli NSosyal test penceresinde B/C/D
   raporunu üret ve bu belgedeki iddiaları güncelle.
7. Keşif dağıtımını başlat; ilk anlamlı A/B sonucu gelene kadar ürün dili
   "gözlemsel / desteklenen pencere" olarak kalır.
