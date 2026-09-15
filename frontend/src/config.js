/**
 * Single control point for every tunable value in the frontend.
 *
 * Mirrors `backend/config.py`: no other module in `src/` should hold a magic
 * number or read `import.meta.env` directly. Values come from Vite env vars so
 * a deployment can retune without a code change; the defaults below are the
 * same ones documented in `.env.example`.
 */
const env = import.meta.env || {};

/** Positive number, or the fallback when unset or nonsense. */
const num = (raw, fallback) => {
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : fallback;
};

export const config = {
  // --- Transport -----------------------------------------------------------
  /** "mock" | "backend" | "contract"; see services/pusula/index.js. */
  apiMode: env.VITE_API_MODE || "mock",
  apiBaseUrl: env.VITE_API_BASE_URL || "/api",
  /** Default per-request budget. */
  requestTimeoutMs: num(env.VITE_REQUEST_TIMEOUT_MS, 20000),
  /**
   * The advisor runs Gemma on CPU and answers in tens of seconds, so it needs
   * a far larger budget than a normal request. Must stay under the provider's
   * own `GEMMA_TIMEOUT_SECONDS`, or the client gives up before the server does.
   */
  advisorTimeoutMs: num(env.VITE_ADVISOR_TIMEOUT_MS, 120000),
  /** Uploads carry up to `maxVideoMb` and the server decodes them with ffmpeg. */
  mediaUploadTimeoutMs: num(env.VITE_MEDIA_UPLOAD_TIMEOUT_MS, 180000),

  // --- Behaviour -----------------------------------------------------------
  /** Sharing windows are computed in this zone unless a caller supplies one. */
  timeZone: env.VITE_TIME_ZONE || "Europe/Istanbul",
  /**
   * Must match `MAX_IMAGE_MB` / `MAX_VIDEO_MB` in backend/config.py, which
   * enforce the same limits server-side. These are only an early, friendlier
   * rejection; the server is the authority.
   */
  maxImageMb: num(env.VITE_MAX_IMAGE_MB, 10),
  maxVideoMb: num(env.VITE_MAX_VIDEO_MB, 50),
  /** Mirrors `detect_media_kind` in backend/services/media_analysis.py. */
  acceptedUploadTypes:
    env.VITE_ACCEPTED_UPLOAD_TYPES ||
    "image/jpeg,image/png,image/webp,video/mp4,video/mov,video/webm",
  /** How long each narrated stage of an advisor call shows before advancing. */
  analysisStageSeconds: num(env.VITE_ANALYSIS_STAGE_SECONDS, 6),
};

export default config;
