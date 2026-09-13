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
export interface Slot {
  id: string;
  day: string;
  time: string;
  startsAt: string;
  timeZone: string;
  onlinePercent: number;
  reach: number;
  format: string;
  label: string;
}
export interface Recommendations {
  confidence: number;
  updatedAt: string;
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
  confidence: number;
  reachMin: number;
  reachMax: number;
  saveMultiplier: number;
  commentProbability: number;
  liftPercent: number;
  bestTime: string;
  alternativeTime: string;
  hashtags: string[];
  tip: string;
  draft: string;
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
