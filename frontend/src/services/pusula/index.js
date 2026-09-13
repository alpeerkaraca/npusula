import { createBackendPusulaApi } from "./backendAdapter.js";
import { createHttpPusulaApi } from "./httpAdapter.js";
import { createMockPusulaApi } from "./mockAdapter.js";

const env = import.meta.env || {};
/**
 * `mock`    - sample data, "Demo veriler" badge.
 * `backend` - the real NPusula FastAPI service; responses are mapped onto the
 *             UI contract by backendAdapter (see services/pusula/backendAdapter.js).
 * `contract` - a backend that natively implements the /v1/pusula/* contract
 *             described in docs/backend-integration.md. Nothing serves it yet.
 */
export const MODES = {
  mock: () => createMockPusulaApi(),
  backend: () => createBackendPusulaApi({ baseUrl: env.VITE_API_BASE_URL || "/api" }),
  contract: () => createHttpPusulaApi({ baseUrl: env.VITE_API_BASE_URL || "/api" }),
};
export const apiMode = env.VITE_API_MODE || "mock";
if (!Object.hasOwn(MODES, apiMode))
  throw new Error(`VITE_API_MODE must be one of ${Object.keys(MODES).join(", ")}`);
export const pusulaApi = MODES[apiMode]();
