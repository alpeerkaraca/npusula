# nSosyal / NPusula

React + Vite arayüzü. Son tasarım kaynağı `design-reference/latest/` içindeki dört NPusula ekranıdır: **kurulum → hazırlık → paylaşım saatleri → fikir danışmanı**. Mevcut sosyal akış ve diğer sayfalar korunur.

## Çalıştırma

```sh
pnpm install
pnpm dev
```

`pnpm build` üretim derlemesini, `pnpm test` API ve UI kontrollerini çalıştırır. `social-clone.jsx` uyumluluk için `src/App.jsx` bileşenini dışa aktarır.

## Yapı

- `src/components/`: ortak yerleşim ve arayüz parçaları.
- `src/pages/`: sosyal ağ sayfaları.
- `src/features/feed/`: gönderi bileşenleri ve mevcut etkileşimler.
- `src/features/pusula/views/`: son tasarımın dört ekranı.
- `src/features/pusula/components/`: API verisiyle çizilen saat ve analiz kartları.
- `src/features/pusula/PusulaProvider.jsx`: kullanıcı akışları.
- `src/services/pusula/`: HTTP/mock adaptörleri, tipler ve yanıt doğrulaması.
- `src/hooks/useApiTask.js`: iptal, yüklenme, hata ve eski yanıtların elenmesi.
- `src/styles/`: tasarım stilleri ve responsive düzen.

## Backend bağlantısı

Varsayılan mod `mock`: ekranlar örnek yanıtlarla çalışır. HTTP modunda sonuçlar yalnızca backend'den gelir; hata durumunda mock veriye dönülmez. Model anahtarları tarayıcıya konmaz.

`.env.local` örneği:

```dotenv
VITE_API_MODE=http
VITE_API_BASE_URL=/api
API_PROXY_TARGET=http://127.0.0.1:8000
```

Değişiklikten sonra geliştirme sunucusunu yeniden başlatın. Ayrıntılı endpoint sözleşmeleri ve entegrasyon adımları: [docs/backend-integration.md](docs/backend-integration.md).

Model çalıştırma, Qdrant bağlantısı ve gerçek gönderi yayını bu aşamada backend tarafına bırakılmıştır. WebDAV'dan indirilen dosyalar `remote-files/` altında durur. Mevcut `.env` gizli bağlantı bilgileri istemci koduna aktarılmaz.
