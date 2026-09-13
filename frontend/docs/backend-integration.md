# Backend ve model entegrasyonu

Arayüzün son tasarım kaynağı `design-reference/latest/` altındaki dört ekrandır. Çalışan React kodu `src/features/pusula/` altındadır. Statik HTML betikleri kullanılmaz.

## Çalışma modları

`VITE_API_MODE` üç değer alır:

- **`backend`** — gerçek NPusula FastAPI servisi. Yanıtlar `backendAdapter.js` içinde arayüz sözleşmesine çevrilir. Örnek veriye **düşülmez**.
- **`contract`** — `/v1/pusula/*` sözleşmesini doğrudan uygulayan bir backend için `httpAdapter.js`. Bugün bunu sunan bir servis yok; sözleşme referansı olarak duruyor.
- **`mock`** (varsayılan) — örnek yanıtlar; ekranda Demo etiketi görünür. Mock plan kaydı gerçek yayın veya bildirim oluşturmaz.

`frontend/.env.local` içinde (Vite `frontend/` dizininden çalışır):

```dotenv
VITE_API_MODE=backend
VITE_API_BASE_URL=/api
API_PROXY_TARGET=http://127.0.0.1:8000
```

Vite sunucusunu yeniden başlatın. Proxy `/api` önekini **olduğu gibi** iletir; backend zaten tüm rotalarını `/api` altında sunar. Adaptör de backend'in kendi yollarını (`/recommend/advisor`, `/profile/{id}/interests`) çağırır, dolayısıyla `baseUrl` ile birlikte tam yol oluşur. Üretimde `/api` için aynı yönlendirme web sunucusunda yapılmalıdır; Vite proxy ayarı üretim derlemesine taşınmaz.

Konteynerleştirilmiş backend'e Windows localhost'tan erişilemez (Podman VM'i 8000'i yayınlar ama ana makineye iletmez). Podman VM IP'sini kullanın — `podman machine ssh <vm> "ip -4 addr show eth0"` — örn. `http://172.17.78.187:8000`.

HTTP modunda bağlantı, yetki veya şema hatası örnek veriyle gizlenmez. Hata ve yeniden deneme arayüzü gösterilir. HTTP modunda gerçek backend hazır olmadan sonuç görüntülenmez.

`VITE_*` değerleri tarayıcıya açıktır. Model anahtarları, WebDAV bilgileri ve servis kimlik bilgileri yalnızca backend'de tutulmalıdır. Mevcut `.env` WebDAV değerleri değiştirilmedi ve API istemcisine taşınmadı. İstemci varsayılan olarak aynı origin oturum cookie'lerini kullanır. Backend oturum yetkisini ve gerekiyorsa CSRF korumasını sağlamalıdır; kullanıcı kimliği istemciden gelen metne göre belirlenmemelidir.

## Katmanlar

- `src/services/apiClient.js`: JSON taşıma, 20 saniye zaman aşımı, iptal, HTTP hataları ve idempotency başlığı.
- `src/services/pusula/httpAdapter.js`: endpoint eşlemesi; UI bu dosyaya doğrudan bağımlı değildir.
- `src/services/pusula/mockAdapter.js`: aynı arayüzü sağlayan demo servis.
- `src/services/pusula/contracts.js`: yanıtlar için çalışma zamanı doğrulaması.
- `src/services/pusula/types.d.ts`: istek/yanıt ve servis tipleri.
- `src/hooks/useApiTask.js`: yükleme, hata, sonuç, iptal ve eski yanıtların elenmesi.
- `PusulaProvider.jsx`: kullanıcı akışları. Butonlar metin eşleştirme yerine açık `prepare`, `analyze`, `plan`, `openDraft` eylemlerini çağırır.
- `components/AnalysisResult.jsx` ve `components/SlotCard.jsx`: tamamen API verisiyle çizilen sonuçlar.

Başka bir backend şeması kullanıldığında dönüşümü `httpAdapter.js` içinde yapın. Görsel bileşenler değişmemelidir. Yeni bir model servisi sağlayıcısı için `PusulaApi` tipini uygulayan başka bir adaptör eklenebilir.

## Endpoint sözleşmesi (v1)

Tüm başarılı yanıtlar JSON nesnesidir; aşağıdaki örneklerde ek bir `data` zarfı yoktur. İlgili tiplerin tamamı `types.d.ts` dosyasındadır.

### Hesap kurulumu

`PUT /v1/pusula/profile`

İstek ve yanıt:

```json
{"interests":["teknoloji","yazilim","yapayzekâ"]}
```

2–5 alan kabul edilir. UI alan kimlikleri: `teknoloji`, `araba`, `yazilim`, `oyun`, `yasam`, `yapayzekâ`, `tasarim`, `bilim`, `girisimcilik`.

### Hazırlık işi

`POST /v1/pusula/preparations` aynı profil gövdesini alır. `GET /v1/pusula/preparations/{id}` işin güncel durumunu verir.

```json
{"id":"job-123","status":"running","progress":42,"message":"Kitle sinyalleri hazırlanıyor"}
```

`status`: `queued`, `running`, `completed`, `failed`. `progress`: 0–100. İş bitince `completed` ve 100 gönderilmesi beklenir. Hata mesajı kullanıcıya gösterilebilir olmalı, hassas ayrıntı içermemelidir. Arayüz saniyede bir sorgular; sayfadan çıkış sorgulamayı durdurur, backend işini silmez. 300 sorgu sonrasında kullanıcıya tekrar kontrol seçeneği gösterilir. Belirsiz bir POST hatası yeniden denendiğinde aynı idempotency anahtarı korunur; bilinen başarısız iş için yeni anahtar oluşturulur.

### Paylaşım önerileri

`GET /v1/pusula/recommendations`

```json
{
  "confidence":94,
  "updatedAt":"2026-09-14T12:00:00Z",
  "slots":[{
    "id":"slot-1","day":"Salı","time":"20:30",
    "startsAt":"2026-09-15T17:30:00Z","timeZone":"Europe/Istanbul",
    "onlinePercent":85,"reach":45000,
    "format":"Kısa Video / Medya Gönderisi",
    "label":"En Yüksek Etkileşim (Peak Slot)"
  }]
}
```

En fazla üç öneri döndürülür. `slots: []` geçerli bir boş durumdur. Saat kartları, yüzdeler, erişim sayıları ve güncelleme zamanı bu yanıttan gelir. `startsAt` mutlak ISO zamanıdır; planlamada görsel gün/saat metni parse edilmez.

### Fikir analizi

`POST /v1/pusula/analyses`

```json
{"text":"Yeni içerik fikri","format":"video","interests":["teknoloji","yazilim"]}
```

`text`: kırpılmış 1–500 karakter. `format`: `video`, `image`, `thread`.

```json
{
  "id":"analysis-1","modelVersion":"pusula-v1","confidence":88,
  "reachMin":34500,"reachMax":52000,"saveMultiplier":4.8,
  "commentProbability":76,"liftPercent":38,
  "bestTime":"Cuma 21:00","alternativeTime":"Cumartesi 11:30–13:00",
  "hashtags":["YapayZeka","Yazılım"],
  "tip":"İlk saniyelerde ana fikri gösterin.",
  "draft":"Modele göre düzenlenmiş içerik taslağı"
}
```

Etiketler `#` olmadan döner. Erişim sayıları ham sayı olmalıdır, `34.5B` gibi biçimlenmiş metin olmamalıdır. İstek sürerken metin/format değişirse önceki analiz iptal edilir ve eski sonuç gösterilmez. Sonuçlar React metni olarak işlenir; HTML çalıştırılmaz. Model 20 saniyeden uzun sürecekse analizi de ayrı bir iş/polling sözleşmesine taşıyın.

### Plan ve taslak kaydı

`POST /v1/pusula/plans`

```json
{"slotId":"slot-1","startsAt":"2026-09-15T17:30:00Z","timeZone":"Europe/Istanbul","text":"Taslak","format":"video"}
```

Yanıt:

```json
{"id":"plan-1","slotId":"slot-1","startsAt":"2026-09-15T17:30:00Z","status":"scheduled"}
```

`status` için `scheduled` veya `saved` kabul edilir. Backend slot sahipliği, saat geçerliliği, yayın yetkisi ve gerçek zamanlama işlemini doğrulamalıdır.

`POST /v1/pusula/drafts`

```json
{"text":"Düzenlenmiş taslak","format":"video"}
```

Yanıt:

```json
{"id":"draft-1","text":"Düzenlenmiş taslak","format":"video"}
```

Başarılı kayıttan sonra gönderi alanı sunucunun döndürdüğü metinle açılır. Bu işlem gönderiyi yayınlamaz.

POST istekleri `Idempotency-Key` taşır. Sunucu bu anahtarı oturum/kullanıcı ve endpoint ile birlikte ele alıp aynı işlemi tekrar uygulamamalıdır. İstemci mutasyonları otomatik tekrar göndermez. Backend istek gövdesini ve yetkileri ayrıca doğrulamalıdır.

## Testler ve sınırlar

`pnpm test`: API sözleşmesi, iptal, zaman aşımı, HTTP hataları ve UI testleri. Gerçek model dosyaları, Qdrant veya yayın sağlayıcısı henüz bağlanmadı. Bu çalışma frontend entegrasyon altyapısını sağlar; backend/model yürütücüsünü içermez. `.joblib` dosyaları tarayıcıda yüklenmez; backend uygun Python ortamında model sürümü ve bağımlılıklarıyla çalıştırmalıdır.
# Bu repository ile entegrasyon durumu

`backend` modu kök dizindeki FastAPI servisine bağlanır. Dönüşüm `src/services/pusula/backendAdapter.js` içindedir; `httpAdapter.js` yalnızca `/v1/pusula/*` sözleşmesini doğrudan uygulayan bir backend için referans olarak durur.

## Eşleme

| Ekran verisi | Backend kaynağı |
|---|---|
| Paylaşım pencereleri | `GET /api/recommend/quick/{user_id}` (`windows[]`) |
| Fikir analizi | `POST /api/recommend/advisor` |
| İlgi alanları | `PUT /api/profile/{user_id}/interests` |
| Plan / taslak kaydı | `POST /api/plans`, `POST /api/drafts` |

Eşlenen alanlar: `day`←`weekday`, `time`←`time_range_local`, `startsAt`←`window_start_utc`, `tip`←`explanation`, `hashtags`←`suggested_tags` (`#` kırpılır), `bestTime`/`alternativeTime`←`windows[0..1]`, `modelVersion`←`model_version`.

## Karşılığı olmayan alanlar

Backend'in üretmediği alanlar arayüzden **kaldırıldı**; yerlerine gerçek metrikler kondu, uydurma sayı üretilmedi:

| Kaldırılan | Yerine gelen |
|---|---|
| `reach`, `reachMin/Max` | `support_post_count`, `support_user_count` |
| `saveMultiplier` | `observational_time_lift` + güven aralığı |
| `commentProbability` | `relative_potential` |
| `onlinePercent` | pencereler arası konum (döndürülen küme içinde sıra) |
| `confidence` (0-100) | `confidence_label` + `confidence` (high/medium/low) |
| `draft` | yok — buton kullanıcının kendi fikrini gönderi alanına taşır |
| `slot.format`, `slot.label` | `evidence_level` |

`observational_time_lift` ve `relative_potential` **popülerlik-skoru biriminde işaretli artıklardır** (`backend/services/recommendation.py`), yüzde değildir; bu yüzden `+0.04` gibi işaretli sayı olarak gösterilirler.

## Gecikme

`POST /api/recommend/advisor` CPU'da Gemma çalıştırdığı için 30–45 sn sürer. Varsayılan 20 sn istemci zaman aşımı bu çağrı için `backendAdapter.js` içinde 120 sn'ye çıkarılır; yükleniyor ekranı gerçek süreyi ve aşama mesajlarını gösterir. Yüzde çubuğu **yoktur** — backend aşama sınırı bildirmediği için yüzde uydurma olurdu. Bu çağrı hâlâ bir iş/kuyruk sözleşmesine taşınmayı hak ediyor; eşik 20 sn değil, kullanıcı deneyimidir.

## Kimlik ve yetki

`user_id` tarayıcıda üretilip `localStorage`'da saklanır; backend'de kimlik doğrulama yoktur, dolayısıyla her istemci herhangi bir `user_id` için ilgi alanı yazabilir. Bu uç halka açılmadan önce kimlik doğrulama eklenmelidir. `GET /api/demo-users` küratörlü demo listesi eksik olduğu için boş döner; runtime'da yazılan ilgi alanları `data/state/declared_topics.json` altında ayrı tutulur ve demo listesine sızmaz.
