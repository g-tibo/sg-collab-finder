import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0a0a0a",
        paper: "#fafaf9",
        accent: "#d13438", // a Singapore red nod
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "Inter", "Arial"],
      },
    },
  },
} satisfies Config;
