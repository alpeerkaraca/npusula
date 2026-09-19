import { config } from "../config.js";

export class ApiError extends Error {
  constructor(message, { status = 0, code = "NETWORK_ERROR" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** Cookie-based API client. Server secrets never belong in VITE_* variables. */
export function createApiClient({
  baseUrl = config.apiBaseUrl,
  fetchImpl = globalThis.fetch,
  timeoutMs: defaultTimeoutMs = config.requestTimeoutMs,
} = {}) {
  return async function request(
    path,
    { method = "GET", body, signal, requestId, timeoutMs = defaultTimeoutMs } = {},
  ) {
    const controller = new AbortController();
    const abort = () => controller.abort(signal?.reason);
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    try {
      // A FormData body must reach fetch untouched: only the browser knows the
      // multipart boundary, so setting Content-Type here would break parsing.
      const isForm =
        typeof FormData !== "undefined" && body instanceof FormData;
      const headers = { Accept: "application/json" };
      if (body !== undefined && !isForm)
        headers["Content-Type"] = "application/json";
      if (requestId) headers["Idempotency-Key"] = requestId;
      const response = await fetchImpl(`${baseUrl.replace(/\/$/, "")}${path}`, {
        method,
        headers,
        credentials: "same-origin",
        signal: controller.signal,
        ...(body !== undefined
          ? { body: isForm ? body : JSON.stringify(body) }
          : {}),
      });
      if (!response.ok) {
        let serverMessage = "";
        try {
          const raw = await response.text();
          if (raw) {
            try {
              const data = JSON.parse(raw);
              if (typeof data === "string") {
                serverMessage = data;
              } else if (typeof data?.detail === "string") {
                serverMessage = data.detail;
              } else if (Array.isArray(data?.detail) && data.detail.length > 0) {
                serverMessage = data.detail
                  .map((item) =>
                    typeof item === "string"
                      ? item
                      : item.msg || JSON.stringify(item),
                  )
                  .join(", ");
              } else if (typeof data?.message === "string") {
                serverMessage = data.message;
              } else if (typeof data?.error === "string") {
                serverMessage = data.error;
              }
            } catch {
              if (!raw.startsWith("<")) {
                serverMessage = raw.slice(0, 300);
              }
            }
          }
        } catch {}

        const messages = {
          401: "Oturumunuz sona erdi. Yeniden giriş yapın.",
          403: "Bu işlem için yetkiniz yok.",
          429: "Çok fazla istek gönderildi. Biraz sonra tekrar deneyin.",
        };
        throw new ApiError(
          serverMessage ||
            messages[response.status] ||
            "Servis isteği tamamlanamadı. Tekrar deneyin.",
          { status: response.status, code: `HTTP_${response.status}` },
        );
      }
      try {
        return await response.json();
      } catch {
        throw new ApiError("Servisten geçersiz JSON yanıtı geldi.", {
          code: "INVALID_RESPONSE",
        });
      }
    } catch (error) {
      if (timedOut)
        throw new ApiError("İstek zaman aşımına uğradı. Tekrar deneyin.", {
          code: "TIMEOUT",
        });
      if (signal?.aborted || error.name === "AbortError") throw error;
      if (error instanceof ApiError) throw error;
      throw new ApiError("Sunucuya ulaşılamadı. Bağlantınızı kontrol edin.");
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  };
}
