import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["apple-touch-icon.png"],
      manifest: {
        name: "Baby Daily Tracker",
        short_name: "Baby Tracker",
        description:
          "Catatan harian tumbuh kembang bayi — menyusui, tidur, popok, vaksinasi, dan lainnya.",
        theme_color: "#FFF8F0",
        background_color: "#FFF8F0",
        display: "standalone",
        orientation: "portrait",
        start_url: "/",
        scope: "/",
        icons: [
          {
            src: "icon-192.png",
            sizes: "192x192",
            type: "image/png",
          },
          {
            src: "icon-512.png",
            sizes: "512x512",
            type: "image/png",
          },
          {
            src: "maskable-icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // API request (ke backend Flask) jangan di-cache offline — data harus selalu fresh
        navigateFallbackDenylist: [/^\/api\//],
        globPatterns: ["**/*.{js,css,html,png,svg,ico}"],
      },
    }),
  ],
  server: {
    port: 5173,
    host: true, // buka ke jaringan WiFi lokal, biar HP bisa akses (npm run dev)
  },
});
