/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        fl: {
          bg: "#12141a",
          panel: "#1a1d26",
          card: "#222634",
          border: "#2d3345",
          orange: "#ff8400",
          accent: "#38bdf8",
        }
      }
    },
  },
  plugins: [],
}

