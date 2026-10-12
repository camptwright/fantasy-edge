/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Navy-tinted slate (FantasyPros My Playbook-style dark surfaces), shared by every screen.
        slate: {
          50: "#f5f7fb", 100: "#eef2f8", 200: "#d9e0ec", 300: "#b8c3d6", 400: "#8d9ab3",
          500: "#5f6d89", 600: "#3a4763", 700: "#26324b", 800: "#18233a", 900: "#0e1729", 950: "#070d1a",
        },
        bg: "#0b0f14",
        surface: "#131a22",
        border: "#212b36",
        accent: "#22c55e",
      },
    },
  },
  plugins: [],
};
