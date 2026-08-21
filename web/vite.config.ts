import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { VitePWA } from "vite-plugin-pwa";

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "prompt",
      includeAssets: [
        "favicon.ico",
        "icon-source.png",
        "apple-touch-icon.png",
        "pwa-*.png",
      ],
      manifest: {
        name: "MDLogger - 마스터 듀얼 전적 기록기",
        short_name: "MDLogger",
        description: "유희왕 마스터 듀얼 점수전·랭크전 전적 기록 및 통계 웹앱",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#0F172A",
        theme_color: "#0F172A",
        orientation: "any",
        lang: "ko",
        categories: ["games", "utilities"],
        icons: [
          {
            src: "/pwa-192x192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "/pwa-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "/pwa-maskable-192x192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "maskable",
          },
          {
            src: "/pwa-maskable-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff2}"],
        runtimeCaching: [
          {
            // Supabase API 및 Auth 요청은 절대 캐시하지 않음 (Network-Only)
            urlPattern: /^https:\/\/.*\.supabase\.co\/.*/i,
            handler: "NetworkOnly",
          },
        ],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/auth\/callback/],
      },
    }),
  ],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
