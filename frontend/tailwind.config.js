/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        void: {
          DEFAULT: "#FFFAF6",
          card: "#FFFFFF",
          raised: "#FFF3EA",
          hairline: "#EEE5DE",
        },
        ink: {
          DEFAULT: "#342F2B",
          muted: "#756B64",
          faint: "#A99D95",
        },
        feed: { DEFAULT: "#FF8068", soft: "#FFF0EB" },
        sleep: { DEFAULT: "#8F79E8", soft: "#F1EDFF" },
        diaper: { DEFAULT: "#4DBE9B", soft: "#EAF8F2" },
        sky: { DEFAULT: "#5A9BEF", soft: "#EDF5FF" },
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
        soft: "0 10px 35px -14px rgba(74, 63, 53, 0.18)",
        nav: "0 -8px 30px rgba(74, 63, 53, 0.08)",
      },
    },
  },
  plugins: [],
};
