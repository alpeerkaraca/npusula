import { config } from "../../config.js";
import { createBackendPusulaApi } from "./backendAdapter.js";
import { createHttpPusulaApi } from "./httpAdapter.js";
import { createMockPusulaApi } from "./mockAdapter.js";

/**
 * `mock`     - sample data, "Demo veriler" badge.
 * `backend`  - the real NPusula FastAPI service; responses are mapped onto the
 *              UI contract by backendAdapter.
 * `contract` - a backend that natively implements the /v1/pusula/* contract
 *              described in docs/backend-integration.md. Nothing serves it yet.
 *
 * The mode and base URL come from src/config.js, not from the environment here.
 */
export const MODES = {
  mock: () => createMockPusulaApi(),
  backend: () => createBackendPusulaApi({ baseUrl: config.apiBaseUrl }),
  contract: () => createHttpPusulaApi({ baseUrl: config.apiBaseUrl }),
};
export const apiMode = config.apiMode;
// Identity lives with the adapter that reads it, but the provider should not
// reach past this facade to get it.
export { USER_ID_KEY, mintUserId, resolveUserId, setUserId } from "./backendAdapter.js";
if (!Object.hasOwn(MODES, apiMode))
  throw new Error(`VITE_API_MODE must be one of ${Object.keys(MODES).join(", ")}`);
export const pusulaApi = MODES[apiMode]();
