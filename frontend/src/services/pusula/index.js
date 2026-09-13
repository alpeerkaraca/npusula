import { createHttpPusulaApi } from "./httpAdapter.js";
import { createMockPusulaApi } from "./mockAdapter.js";
const env = import.meta.env || {};
export const apiMode = env.VITE_API_MODE || "mock";
if (!["mock", "http"].includes(apiMode))
  throw new Error("VITE_API_MODE must be mock or http");
export const pusulaApi =
  apiMode === "http"
    ? createHttpPusulaApi({ baseUrl: env.VITE_API_BASE_URL || "/api" })
    : createMockPusulaApi();
