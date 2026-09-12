# NOTICE — Üçüncü Taraf Veri Kaynakları / Third-Party Data Sources

Bu proje, içerik moderasyonu guardrail'inin ML sınıflandırıcı eğitiminde ve
lexicon kürasyonunda aşağıdaki açık kaynak veri kaynaklarını kullanır.
Bu veriler repository içinde dağıtılmaz; yalnızca
`scripts/train_guardrail_model.py` tarafından eğitim sırasında indirilir.

## Turkish Offensive Language corpus (troff-v1.0)

- **Creator:** Çağrı Çöltekin
- **Citation:** Çöltekin, Çağrı (2020). *A Corpus of Turkish Offensive Language on Social Media.* In Proceedings of the 12th Language Resources and Evaluation Conference (LREC 2020), pages 6174–6184.
- **URL:** https://coltekin.github.io/offensive-turkish/
- **License:** CC-BY (attribution required)
- **Usage:** Ana ML eğitim verisi (35.284 etiketli tweet)

## teamgzg/Datasets

- **URL:** https://github.com/teamgzg/Datasets
- **License:** Apache-2.0
- **Usage:** Takviye eğitim verisi (ırkçı/küfür/hakaret/cinsiyetçi örnekler)

## @badwords/languages — Turkish word list

- **URL:** https://github.com/FlacSy/badwords (npm: `@badwords/languages`)
- **License:** MIT
- **Usage:** Lexicon aday kürasyonu (1.031 kelime, troff ile doğrulandı)

## censor-text/profanity-list — Turkish list (`list/tr.txt`)

- **URL:** https://github.com/censor-text/profanity-list
- **License:** Unlicense (public domain)
- **Usage:** Lexicon aday kürasyonu (127 kayıt)
