/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        void: {
          DEFAULT: "#FFF8F0",
          card: "#FFFFFF",
          raised: "#FFF1DE",
          hairline: "#F0E2CC",
        },
        ink: {
          DEFAULT: "#4A3F35",
          muted: "#9C8F82",
          faint: "#C7BAA9",
        },
        feed: { DEFAULT: "#FFA733", soft: "#FFF1D9" },
        sleep: { DEFAULT: "#9B87E0", soft: "#EFEAFB" },
        diaper: { DEFAULT: "#4FC9A8", soft: "#E1F8F1" },
        warn: { DEFAULT: "#FF7A5C", soft: "#FFE6DF" },
      },
      fontFamily: {
        display: ["'Baloo 2'", "cursive"],
        body: ["'Nunito'", "sans-serif"],
        mono: ["'Nunito'", "sans-serif"],
      },
      borderRadius: {
        xl2: "1.5rem",
      },
      boxShadow: {
        soft: "0 4px 20px -4px rgba(74, 63, 53, 0.08)",
      },
    },
  },
  plugins: [],
};
