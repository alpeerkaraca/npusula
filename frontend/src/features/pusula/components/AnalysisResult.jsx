import React from "react";
import DesignIcon from "../DesignIcon.jsx";
import { evidenceLabel, scoreInterval, signedScore } from "../format.js";
export default function AnalysisResult({
  result,
  onCopy,
  onNew,
  onDraft,
  busy,
}) {
  // Every tile below reads a metric the backend actually computes for the
  // strongest window. Nothing here is a client-side prediction.
  const best = result.windows?.[0];
  const tiles = best
    ? [
        [
          "Destek Gönderisi",
          `${best.supportPostCount.toLocaleString("tr-TR")} gönderi`,
          `${best.supportUserCount.toLocaleString("tr-TR")} kullanıcı`,
        ],
        [
          "Gözlemsel Zaman Etkisi",
          signedScore(best.observationalTimeLift),
          scoreInterval(best.liftCiLow, best.liftCiHigh) ||
            `${best.confidenceLabel} güven`,
        ],
        [
          "Göreli Potansiyel",
          signedScore(best.relativePotential),
          evidenceLabel(best.evidenceLevel),
        ],
      ]
    : [];
  return (
    <section className="p-space-lg rounded-xl bg-surface-container-low shadow-2xl relative overflow-hidden">
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary-container via-secondary-container to-tertiary" />
      <header className="flex flex-col sm:flex-row justify-between gap-space-sm pb-space-lg">
        <div>
          <span className="text-label-sm uppercase text-on-surface-variant">
            2. Çıktı ve Tahminleme Modeli
          </span>
          <h2 className="text-headline-sm font-bold">
            N-Pusula Fikir Değerlendirmesi
          </h2>
          {/* primary_category_confidence is a match-density score, not a
              trained-model probability, so it is captioned as a match score. */}
          <span className="text-code-sm text-on-surface-variant">
            {result.topic} · {result.primaryCategory} · eşleşme{" "}
            {result.primaryCategoryConfidence.toFixed(2)}
          </span>
        </div>
        <span className="self-start px-space-md py-1.5 rounded-full bg-tertiary-container/20 text-tertiary text-label-md font-bold">
          {result.confidenceLabel} Güven
        </span>
      </header>
      {tiles.length ? (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-space-md pb-space-lg">
          {tiles.map(([label, value, detail]) => (
            <div
              className="p-space-md rounded-xl bg-surface-container flex flex-col gap-1"
              key={label}
            >
              <span className="text-label-sm text-on-surface-variant">
                {label}
              </span>
              <strong className="text-headline-sm text-primary">{value}</strong>
              <span className="text-code-sm text-tertiary">{detail}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="request-state pb-space-lg">
          Bu fikir için desteklenen bir paylaşım penceresi bulunamadı.
        </div>
      )}
      <section className="p-space-lg rounded-xl bg-gradient-to-br from-surface-container to-surface-container-high mb-space-lg">
        <div className="flex items-start gap-space-md">
          <span className="w-12 h-12 rounded-xl bg-primary-container text-on-primary-container flex items-center justify-center shrink-0">
            <DesignIcon name="schedule" className="text-[26px]" />
          </span>
          <div>
            <span className="text-label-sm text-primary uppercase">
              Zamanlama Optimizasyonu
            </span>
            <p className="text-title-md font-bold">
              Bu içerik için en uygun paylaşım zamanı:{" "}
              <span className="text-primary underline">{result.bestTime}</span>
            </p>
            <p className="text-body-md text-on-surface-variant mt-space-sm">
              {result.tip}
            </p>
          </div>
        </div>
        <div className="mt-space-md p-space-sm rounded-lg bg-surface-container-lowest/40 text-body-sm">
          Alternatif aralık: {result.alternativeTime}
        </div>
      </section>
      <section className="flex flex-col gap-space-sm pb-space-lg">
        <header className="flex justify-between gap-2">
          <h3 className="text-title-sm font-semibold">
            <DesignIcon name="tag" /> Otomatik Önerilen Etkileşim Etiketleri
          </h3>
          <button
            onClick={onCopy}
            className="text-primary text-label-sm bg-surface-container-high rounded-lg px-2"
          >
            <DesignIcon name="content_copy" /> Tümünü Kopyala
          </button>
        </header>
        <div className="flex flex-wrap gap-2">
          {result.hashtags.map((tag) => (
            <span
              key={tag}
              className="px-3 py-1.5 bg-surface-container rounded-xl text-primary text-label-md"
            >
              #{tag}
            </span>
          ))}
        </div>
      </section>
      <div className="bg-surface-container rounded-xl p-space-md mb-space-lg border-l-4 border-primary text-body-md">
        <strong className="text-primary">Kritik AI Rezonans İpucu</strong>
        <p className="mt-space-xs">{result.tip}</p>
      </div>
      <div className="flex flex-col sm:flex-row gap-space-sm">
        <button
          className="rounded-full bg-surface-container-high px-space-lg py-space-sm font-semibold"
          onClick={onNew}
        >
          <DesignIcon name="refresh" /> Yeni Fikir Danış
        </button>
        <button
          disabled={busy}
          className="flex-1 rounded-full bg-gradient-to-r from-primary-container to-secondary-container text-on-primary-container px-space-lg py-space-sm font-bold"
          onClick={onDraft}
        >
          <DesignIcon name="edit_document" /> Fikri Gönderi Alanına Aktar
        </button>
      </div>
    </section>
  );
}
