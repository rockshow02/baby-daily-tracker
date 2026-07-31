import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // buka ke jaringan WiFi lokal, biar HP bisa akses (npm run dev)
  },
});
