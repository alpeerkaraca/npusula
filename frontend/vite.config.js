import { defineConfig, loadEnv } from "vite";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    server: {
      // Allow direct navigation to sub-paths (e.g. /assistant) without 404.
      historyApiFallback: true,
      proxy: env.API_PROXY_TARGET
        ? {
            // The FastAPI backend mounts every route under /api, so the prefix
            // is forwarded as-is. Stripping it here sent /api/health to a
            // nonexistent /health and broke every request.
            "/api": {
              target: env.API_PROXY_TARGET,
              changeOrigin: true,
            },
          }
        : undefined,
    },
  };
});
