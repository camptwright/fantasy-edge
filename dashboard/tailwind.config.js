/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0f14",
        surface: "#131a22",
        border: "#212b36",
        accent: "#22c55e",
      },
    },
  },
  plugins: [],
};
