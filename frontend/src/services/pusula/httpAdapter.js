import { createApiClient } from "../apiClient.js";
import { validate, validateAnalysisInput } from "./contracts.js";
/** @returns {import('./types').PusulaApi} */
export function createHttpPusulaApi(options) {
  const request = createApiClient(options);
  const call = async (path, kind, options) =>
    validate(kind, await request(`/v1/pusula${path}`, options));
  return {
    mode: "http",
    saveProfile: (body, options) => {
      validate("profile", body);
      return call("/profile", "profile", { ...options, method: "PUT", body });
    },
    startPreparation: (body, options) =>
      call("/preparations", "job", { ...options, method: "POST", body }),
    getPreparation: (id, options) =>
      call(`/preparations/${encodeURIComponent(id)}`, "job", options),
    getRecommendations: (options) =>
      call("/recommendations", "recommendations", options),
    analyzeIdea: (body, options) => {
      validateAnalysisInput(body);
      return call("/analyses", "analysis", {
        ...options,
        method: "POST",
        body,
      });
    },
    createPlan: (body, options) =>
      call("/plans", "plan", { ...options, method: "POST", body }),
    saveDraft: (body, options) =>
      call("/drafts", "draft", { ...options, method: "POST", body }),
  };
}
