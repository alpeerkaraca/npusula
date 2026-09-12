"""Curated data for the EnPusula moderation guardrail.

This module is intentionally dependency-free (no sklearn/pandas) so the runtime
import stays cheap. Data provenance:

1. UNSAFE_LEXICON: hand-curated plus terms adopted from the MIT-licensed
   @badwords/languages list (https://github.com/FlacSy/badwords) and the
   Unlicense-licensed censor-text/profanity-list
   (https://github.com/censor-text/profanity-list). Every adopted term was
   empirically validated against the Turkish Offensive Language corpus
   (troff-v1.0, Cagri Coltekin 2020, CC-BY; https://coltekin.github.io/offensive-turkish/)
   and is included only when it almost never appears in non-offensive text.
   Terms that appear in ordinary text (e.g. "allah", "ana", "ahmak") are
   deliberately excluded.

2. MODERATION_TRAINING_CORPUS: hand-written balanced fallback corpus used when
   the trained artifact (artifacts/guardrail_classifier.joblib) is missing.
   The production model is trained by scripts/train_guardrail_model.py on real
   datasets (see NOTICE.md).

3. FALSE_POSITIVE_BATTERY / UNSAFE_BATTERY: regression strings used as hard
   constraints during threshold calibration and in tests.
"""

# Deterministic multilingual lexicon of explicit unsafe terms. Word-boundary
# matching only (no substrings), so "sex" does not match "seksiyon" and
# "porn" does not match "pornografik olmayan" phrases the ML model handles.
# The AdversarialNormalizer runs first, so obfuscated variants (n4k3d,
# n.a.k.e.d) are decoded before this check.
UNSAFE_LEXICON: dict[str, str] = {
    # sexual_content: explicit adult terms (TR/EN)
    "cinsel": "sexual_content",
    "ciplak": "sexual_content",
    "çıplak": "sexual_content",
    "naked": "sexual_content",
    "nude": "sexual_content",
    "nudes": "sexual_content",
    "porn": "sexual_content",
    "porno": "sexual_content",
    "pornografi": "sexual_content",
    "pornografik": "sexual_content",
    "xxx": "sexual_content",
    "sex": "sexual_content",
    "sexy": "sexual_content",
    "escort": "sexual_content",
    "hentai": "sexual_content",
    "onlyfans": "sexual_content",
    "fetish": "sexual_content",
    "striptiz": "sexual_content",
    "seks": "sexual_content",
    "sikiş": "sexual_content",
    "mastürbasyon": "sexual_content",
    "erotik": "sexual_content",
    "müstehcen": "sexual_content",
    # sexual_content: Turkish profanity roots and their common inflections
    # (adopted from MIT/Unlicense lists, validated against troff: zero or near-zero
    # occurrence in non-offensive text)
    "sik": "sexual_content",
    "sike": "sexual_content",
    "sikmek": "sexual_content",
    "siktir": "sexual_content",
    "sikeyim": "sexual_content",
    "sikik": "sexual_content",
    "amcık": "sexual_content",
    "yarrak": "sexual_content",
    "amı": "sexual_content",
    "amına koyayım": "sexual_content",
    "göt": "sexual_content",
    "götü": "sexual_content",
    "götüne": "sexual_content",
    "götün": "sexual_content",
    "götünden": "sexual_content",
    "götüm": "sexual_content",
    "götünü": "sexual_content",
    "götünüz": "sexual_content",
    "götünüzü": "sexual_content",
    "amk": "sexual_content",
    "aq": "sexual_content",
    "amq": "sexual_content",
    # sexual_content: dataset-derived candidates (troff n_offensive>=8, zero safe-doc)
    "amına": "sexual_content",
    "amina": "sexual_content",
    "götveren": "sexual_content",
    "sikerim": "sexual_content",
    "sikim": "sexual_content",
    "sokayım": "sexual_content",
    "sıçayım": "sexual_content",
    "yarak": "sexual_content",
    # hate_speech: insults and slurs (TR)
    "orospu": "hate_speech",
    "oruspu": "hate_speech",
    "orospu çocuğu": "hate_speech",
    "orospu çocukları": "hate_speech",
    "piç": "hate_speech",
    "piçi": "hate_speech",
    "piçler": "hate_speech",
    "ibne": "hate_speech",
    "ibneler": "hate_speech",
    "puşt": "hate_speech",
    "pezevenk": "hate_speech",
    "gavat": "hate_speech",
    "oç": "hate_speech",
    "ananı": "hate_speech",
    "serefsiz": "hate_speech",
    "haysiyetsiz": "hate_speech",
    # hate_speech: dataset-derived candidates (troff zero safe-doc)
    "orosbu": "hate_speech",
    "beyinsiz": "hate_speech",
    "kişiliksiz": "hate_speech",
    "hayasız": "hate_speech",
    # gambling
    "bahis": "gambling",
    "casino": "gambling",
    "kumar": "gambling",
    "kumarhane": "gambling",
    "rulet": "gambling",
    "blackjack": "gambling",
    "poker": "gambling",
    "iddaa": "gambling",
    # violence / self-harm / illicit substances
    "intihar": "violence",
    "suicide": "violence",
    "eroin": "violence",
    "kokain": "violence",
    "metamfetamin": "violence",
    "uyuşturucu": "violence",
    "drugs": "violence",
    "heroin": "violence",
    "cocaine": "violence",
    "meth": "violence",
}

# Benign phrases containing lexicon words that must not trigger a block.
# NOTE: strip_phrase_exceptions uses case-sensitive str.replace, so all
# phrases must be lowercase.
LEXICON_PHRASE_EXCEPTIONS: tuple[str, ...] = (
    "naked eye",
    "poker face",
    "poker yüz",
    "çıplak göz",
)


def strip_phrase_exceptions(text: str) -> str:
    """Removes benign phrases (e.g. 'naked eye', 'çıplak göz') that would
    otherwise be mistaken for unsafe terms by the lexicon or the ML model."""
    for phrase in LEXICON_PHRASE_EXCEPTIONS:
        text = text.replace(phrase, "")
    return text

# Hand-written balanced fallback corpus: standard, leetspeak, and edge examples.
# Used only when the trained artifact is missing; the production model is
# trained by scripts/train_guardrail_model.py on real datasets.
MODERATION_TRAINING_CORPUS: list[tuple[str, str]] = [
    # --- SAFE: Technology, Code, AI, Architecture ---
    ("Python ile yapay zeka modelleri ve derin öğrenme", "safe"),
    ("FastAPI ve Docker ile mikroservis mimarisi kurma", "safe"),
    ("Transformer mimarileri ve dikkat mekanizmaları", "safe"),
    ("Veritabanı indeksleme ve SQL sorgu optimizasyonu", "safe"),
    ("Frontend geliştirmede React ve TypeScript pratikleri", "safe"),
    ("Büyük dil modellerinde quantization ve sıkıştırma", "safe"),
    ("Bulut bilişim ve Kubernetes küme yönetimi", "safe"),
    ("Git branch yönetimi ve sürekli entegrasyon CI CD", "safe"),
    ("Yazılım mimarisi ve temiz kod prensipleri", "safe"),
    ("Mobil uygulama geliştirme ve Flutter ipuçları", "safe"),
    ("PyTorch ile sinir ağları ve DirectML GPU hızlandırma", "safe"),
    ("Açık kaynak kodlu kütüphaneler ve katkı rehberi", "safe"),
    # --- SAFE: Business, Finance, Entrepreneurship ---
    ("Borsa İstanbul ve hisse senedi teknik analiz yöntemleri", "safe"),
    ("Startup kurucuları için tohum yatırım alma rehberi", "safe"),
    ("Kripto para piyasalarında risk yönetimi ve portföy", "safe"),
    ("B2B SaaS şirketlerinde müşteri kazanımı ve büyüme", "safe"),
    ("E-ticaret sitelerinde dönüşüm oranı optimizasyonu", "safe"),
    ("Finansal okuryazarlık ve bütçe planlama teknikleri", "safe"),
    # --- SAFE: Lifestyle, Sports, Art, Education, Health ---
    ("Sabah koşusu ve maraton hazırlık programı", "safe"),
    ("Evde sağlıklı beslenme ve düşük kalorili tarifler", "safe"),
    ("Minimalist yaşam tarzı ve üretkenlik rutinleri", "safe"),
    ("Çağdaş sanat sergileri ve modern fotoğrafçılık", "safe"),
    ("Üniversite sınavına hazırlık ve etkili ders çalışma", "safe"),
    ("Kahve demleme yöntemleri V60 ve Aeropress rehberi", "safe"),
    ("Yeni nesil oyun konsolları ve grafik karşılaştırması", "safe"),
    ("Hafta sonu doğa yürüyüşü ve kamp malzemeleri", "safe"),
    ("Kedilerde beslenme ve veteriner kontrol rehberi", "safe"),
    ("Bahar temizliği ve ev dekorasyonu fikirleri", "safe"),
    ("Pazar kahvaltısı ve dostlarla yürüyüş keyfi", "safe"),
    # --- SAFE: Food, HR, Marketing, Sports, Everyday (false positive prone) ---
    ("patlıcan kebabı tarifi ve ev yemekleri", "safe"),
    ("menemen ve zeytinyağlı yemek tarifleri", "safe"),
    ("kebap tarifi evde nasıl yapılır", "safe"),
    ("insan kaynakları iş ilanları ve mülakat", "safe"),
    ("özgeçmiş hazırlama ve kariyer fırsatları", "safe"),
    ("iş ilanları ve iş başvurusu rehberi", "safe"),
    ("promo kodları ve indirim kampanyası", "safe"),
    ("promosyon ürünleri satış kampanyası", "safe"),
    ("sosyal medya pazarlama stratejileri", "safe"),
    ("spor haberleri maç özeti", "safe"),
    ("futbol taktikleri ve maç analizi", "safe"),
    ("5G teknolojisi ve akıllı telefonlar", "safe"),
    ("mobil oyun geliştirme ve oyun motorları", "safe"),
    ("seyahat rehberi ve gezi planlama", "safe"),
    ("kitap önerileri ve okuma alışkanlığı", "safe"),
    ("müzik aletleri ve gitar dersleri", "safe"),
    ("film eleştirileri ve dizi önerileri", "safe"),
    ("kişisel bakım ve cilt bakımı ürünleri", "safe"),
    ("evcil hayvan eğitimi ve bakımı", "safe"),
    ("ev dekorasyonu ve mobilya seçimi", "safe"),
    # --- SAFE: English (multilingual coverage) ---
    ("artificial intelligence tutorial", "safe"),
    ("machine learning models and training", "safe"),
    ("travel guide and trip planning", "safe"),
    ("football match highlights", "safe"),
    ("healthy recipes and meal prep", "safe"),
    ("job listings and career opportunities", "safe"),
    ("cloud computing and devops practices", "safe"),
    ("photography tips for beginners", "safe"),
    # --- SEXUAL CONTENT / ADULT / NSFW (Standard + Leetspeak) ---
    ("cinsel ilişki ve erotik hikayeler", "sexual_content"),
    ("çıplak kadın ve erkek fotoğrafları", "sexual_content"),
    ("c1pl4q fotoğraflar ve videolar", "sexual_content"),
    ("ciplak pozlar ve resimler", "sexual_content"),
    ("ayak resmi ve ayak fetişi görselleri", "sexual_content"),
    ("4y4k r3sm1 ve f3t1s paylaşımları", "sexual_content"),
    ("ayak fetişi ve çorap fotoğrafları", "sexual_content"),
    ("porno video izle ve adult sahneler", "sexual_content"),
    ("p0rn0 izle hd kalite", "sexual_content"),
    ("erotik pozlar ve iç çamaşırı çekimleri", "sexual_content"),
    ("er0t1k g0rs3ll3r ve nude", "sexual_content"),
    ("nude fotoğraflar ve ifşa arşivi", "sexual_content"),
    ("nvd3 resimler paylasimi", "sexual_content"),
    ("escort numaraları ve eskort servisi", "sexual_content"),
    ("3sc0rt ve j1g0l0 ilanları", "sexual_content"),
    ("onlyfans sızıntıları ve müstehcen pozlar", "sexual_content"),
    ("0nlyf4ns arşivleri", "sexual_content"),
    ("cinsel görsel ayak resmi", "sexual_content"),
    ("c!ns3l g0rs3l 4y4k", "sexual_content"),
    ("cinsel organ ve vajina penis görselleri", "sexual_content"),
    ("mastürbasyon teknikleri ve haz", "sexual_content"),
    ("m4sturb4sy0n ve erotik deneyim", "sexual_content"),
    ("seks partneri bulma ve cinsel sohbet", "sexual_content"),
    ("s3ks s0hb3t ve erotik hat", "sexual_content"),
    # --- GAMBLING / ILLEGAL BETTING (Standard + Leetspeak) ---
    ("canlı bahis ve kaçak iddaa oranları", "gambling"),
    ("c4nl1 b4h1s ve k4c4k 1dd44", "gambling"),
    ("yasadışı bahis siteleri bonus dağıtıyor", "gambling"),
    ("y4s4d1s1 b4h1s giris adresi", "gambling"),
    ("rulet taktikleri ve canlı casino oyunları", "gambling"),
    ("rul3t ve c4s1n0 taktikleri", "gambling"),
    ("sweet bonanza slot oyna büyük kazanç", "gambling"),
    ("sl0t oyna bedava cevirme", "gambling"),
    ("kumarhane siteleri ve para çekme yöntemleri", "gambling"),
    ("kum4r oyna para kazan", "gambling"),
    ("kaçak iddaa kuponları hazır kupon", "gambling"),
    ("bahis sitesi güvenilir giriş", "gambling"),
    ("b4h1s s1t3s1", "gambling"),
    # --- VIOLENCE / WEAPONS / SELF-HARM / ILLICIT ---
    ("intihar yöntemleri ve hayata son verme", "violence"),
    ("1nt1h4r etme rehberi", "violence"),
    ("evde bomba yapımı ve patlayıcı maddeler", "violence"),
    ("b0mb4 yapimi kimyasal karisim", "violence"),
    ("kaçak silah satışı ve ateşli silahlar", "violence"),
    ("s1l4h satisi ruhsatsiz tabanca", "violence"),
    ("suikast planı ve adam öldürme", "violence"),
    ("uyuşturucu maddeler ve hap temini", "violence"),
    ("uyusturucu siparis torbaci", "violence"),
    # --- HATE SPEECH / HARASSMENT ---
    ("etnik temizlik yapılmalı ve hepsi yok edilmeli", "hate_speech"),
    ("bu ırktan olan herkes gebersin aşağılık pislikler", "hate_speech"),
    ("terör propagandası ve silahlı örgüt destekçiliği", "hate_speech"),
    ("bu milleti haritadan silmek lazım topunuzun canı cehenneme", "hate_speech"),
    # --- UNSAFE: English (multilingual coverage) ---
    ("naked girls photos", "sexual_content"),
    ("nude pictures and videos", "sexual_content"),
    ("porn videos online free", "sexual_content"),
    ("sex chat and adult dating", "sexual_content"),
    ("escort service listings", "sexual_content"),
    ("onlyfans leaked content", "sexual_content"),
    ("adult content website", "sexual_content"),
    ("online casino and betting odds", "gambling"),
    ("illegal betting site bonus", "gambling"),
    ("gambling tips and roulette strategy", "gambling"),
    ("suicide methods", "violence"),
    ("how to make a bomb at home", "violence"),
    ("buy drugs online", "violence"),
]

# Regression battery: legitimate everyday/technical texts that MUST pass the
# guardrail (hard constraint during threshold calibration and in tests).
FALSE_POSITIVE_BATTERY: tuple[str, ...] = (
    "Patlıcan kebabı tarifi",
    "kebap tarifi evde",
    "promo",
    "promo kodları ve indirim kampanyası",
    "spor haberleri maç özeti",
    "insan kaynakları iş ilanları",
    "5G teknolojisi ve akıllı telefonlar",
    "yemek tarifleri menemen ve patlıcan",
    "seksiyon tasarımı ve dergi düzeni",
    "poker yüz ifadesi analizi",
    "poker face psychology",
    "çıplak gözle görülebilen yıldızlar",
    "artificial intelligence tutorial",
    "travel guide and trip planning",
    "job listings and career opportunities",
    "football match highlights",
    "Yapay zeka modelleri ve mobil cihazlarda yerel LLM optimizasyonu",
    "Pazar kahvaltısı ve dostlarla doğa yürüyüşü",
    "Python ile yapay zeka",
    "3D yazıcı ve tasarım ipuçları",
    "100 TL altı hediye fikirleri",
    "e-ticaret sitesi açma rehberi",
    "o ve ben",
    "2024 yılı planları",
    "react 18 sürümü",
)

# Regression battery: unsafe texts that MUST be blocked, with expected category.
UNSAFE_BATTERY: tuple[tuple[str, str], ...] = (
    ("porno video izle", "sexual_content"),
    ("Cinsel görsel ayak resmi", "sexual_content"),
    ("c1pl4q", "sexual_content"),
    ("c!ns3l 4y4k r3sm1", "sexual_content"),
    ("eşcinsel seks", "sexual_content"),
    ("seks videoları", "sexual_content"),
    ("b4h1s s1t3s1", "gambling"),
    ("1nt1h4r ve b0mb4 yapimi", "violence"),
    ("intihar yöntemleri", "violence"),
    ("naked girls", "sexual_content"),
    ("online casino betting odds", "gambling"),
    ("buy drugs online", "violence"),
    ("orospu çocuğu", "hate_speech"),
    ("amk yapma şunu", "sexual_content"),
)
