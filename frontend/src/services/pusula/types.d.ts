export type Format = "video" | "image" | "thread";
export interface RequestOptions {
  signal?: AbortSignal;
  requestId?: string;
}
export interface Profile {
  interests: string[];
}
export interface Preparation {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  message: string;
}

/**
 * One sharing window. Every field below maps 1:1 to a field the backend
 * actually computes (`backend/schemas/recommendation.py::RecommendedWindow`);
 * none of it is derived or invented on the client.
 */
export interface Slot {
  id: string;
  /** Turkish weekday name, e.g. "Perşembe". */
  day: string;
  /** Local window range, e.g. "15.00–18.00". */
  time: string;
  /** Authoritative absolute time (window_start_utc). */
  startsAt: string;
  timeZone: string;
  /**
   * Signed residual in popularity-score units, centred on the corpus mean
   * (`lift - mean_lift`), so it may be negative. Not a 0–1 ratio.
   */
  relativePotential: number;
  /**
   * 0–100 position of this window within the returned set, used only for the
   * bar. Derived by the adapter from the real scores; it is a rank, not a score.
   */
  rankPercent: number;
  /** Corpus support behind this window's estimate. */
  supportPostCount: number;
  supportUserCount: number;
  /** Signed residual lift in popularity-score units. Not a percentage. */
  observationalTimeLift: number;
  liftCiLow: number | null;
  liftCiHigh: number | null;
  confidence: "high" | "medium" | "low";
  /** Turkish label for the confidence level. */
  confidenceLabel: string;
  /** How strong the evidence behind this window is. */
  evidenceLevel: string;
}
export interface SimilarPost {
  postId: string;
  title: string;
  /**
   * 0–6 index. Unlike `Slot.day`, the backend's similar-post payload carries a
   * numeric weekday, so it is not labelled as a Turkish day name.
   */
  weekdayIndex: number;
  hour: number;
  popularityScore: number;
  similarity: number;
  tags: string[];
}
export interface Recommendations {
  /** "high" | "medium" | "low" — the backend models confidence as a level. */
  confidence: "high" | "medium" | "low";
  confidenceLabel: string;
  /** Client receipt time; the backend exposes no server timestamp. */
  updatedAt: string;
  activeTopic: string;
  coldStart: boolean;
  timezoneBasis: string;
  explanation: string;
  slots: Slot[];
}
export interface AnalysisInput {
  text: string;
  format: Format;
  interests?: string[];
}
export interface Analysis {
  id: string;
  modelVersion: string;
  topic: string;
  primaryCategory: string;
  /** 0–1 classifier confidence for the primary category. */
  primaryCategoryConfidence: number;
  confidence: "high" | "medium" | "low";
  confidenceLabel: string;
  bestTime: string;
  alternativeTime: string;
  /** Hashtags without the leading "#". */
  hashtags: string[];
  /** Turkish explanation produced by the advisor. */
  tip: string;
  historyDepth: string;
  isTieOrBroadWindow: boolean;
  timezoneBasis: string;
  windows: Slot[];
  similarPosts: SimilarPost[];
}
export interface PlanInput {
  slotId: string;
  startsAt: string;
  timeZone: string;
  text: string;
  format: Format;
}
export interface Plan {
  id: string;
  slotId: string;
  startsAt: string;
  status: "scheduled" | "saved";
}
export interface Draft {
  id: string;
  text: string;
  format: Format;
}
export interface PusulaApi {
  mode: "mock" | "http";
  saveProfile(body: Profile, options?: RequestOptions): Promise<Profile>;
  startPreparation(
    body: Profile,
    options?: RequestOptions,
  ): Promise<Preparation>;
  getPreparation(id: string, options?: RequestOptions): Promise<Preparation>;
  getRecommendations(options?: RequestOptions): Promise<Recommendations>;
  analyzeIdea(body: AnalysisInput, options?: RequestOptions): Promise<Analysis>;
  createPlan(body: PlanInput, options?: RequestOptions): Promise<Plan>;
  saveDraft(body: AnalysisInput, options?: RequestOptions): Promise<Draft>;
}
