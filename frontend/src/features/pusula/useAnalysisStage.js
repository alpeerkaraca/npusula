import { useEffect, useState } from "react";
import { config } from "../../config.js";

/**
 * Narration for the advisor call, which takes 30-45s because Gemma runs on CPU
 * and reports no progress of its own. The stages mirror the order the backend
 * actually works in (backend/services/advisor.py: guardrail -> topic ->
 * category -> retrieval -> tags -> windows -> explanation).
 *
 * No percentage is shown: the backend gives no stage boundaries, so any bar
 * would be invented. Elapsed seconds are real.
 */
const STAGES = [
  "İçerik denetimden geçiriliyor",
  "Konu ve kategori çıkarılıyor",
  "Benzer yüksek performanslı gönderiler taranıyor",
  "Etiketler kategoriye göre doğrulanıyor",
  "Paylaşım pencereleri puanlanıyor",
  "Açıklama üretiliyor",
];

export function useAnalysisStage(active) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!active) return undefined;
    setElapsed(0);
    const started = Date.now();
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [active]);
  if (!active) return null;
  const index = Math.min(
    STAGES.length - 1,
    Math.floor(elapsed / config.analysisStageSeconds),
  );
  return `${STAGES[index]}… (${elapsed} sn)`;
}
