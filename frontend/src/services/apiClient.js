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
  baseUrl = "/api",
  fetchImpl = globalThis.fetch,
  timeoutMs: defaultTimeoutMs = 20000,
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
      const headers = { Accept: "application/json" };
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (requestId) headers["Idempotency-Key"] = requestId;
      const response = await fetchImpl(`${baseUrl.replace(/\/$/, "")}${path}`, {
        method,
        headers,
        credentials: "same-origin",
        signal: controller.signal,
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      });
      if (!response.ok) {
        const messages = {
          401: "Oturumunuz sona erdi. Yeniden giriş yapın.",
          403: "Bu işlem için yetkiniz yok.",
          429: "Çok fazla istek gönderildi. Biraz sonra tekrar deneyin.",
        };
        throw new ApiError(
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
