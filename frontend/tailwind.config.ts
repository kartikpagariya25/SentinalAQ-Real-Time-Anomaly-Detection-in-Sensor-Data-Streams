import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#111217",
        surface: { base: "#181b1f", raised: "#22252b" },
        text: {
          primary: "rgb(204,204,220)",
          secondary: "rgba(204,204,220,0.65)",
          disabled: "rgba(204,204,220,0.61)",
          maxContrast: "#ffffff",
        },
        border: {
          weak: "rgba(204,204,220,0.12)",
          DEFAULT: "rgba(204,204,220,0.2)",
          strong: "rgba(204,204,220,0.30)",
        },
        status: {
          normal: "#1a7f4b",
          normalText: "#6ccf8e",
          fault: "#d10e5c",
          faultText: "#ff5286",
          drift: "#ff9900",
          driftText: "#fbad37",
          event: "#3d71d9",
          eventText: "#6e9fff",
        },

        // shadcn/ui component tokens — mapped to design.md's dark palette
        // via CSS variables in src/index.css (single dark theme, no toggle).
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        input: "var(--input)",
        ring: "var(--ring)",
      },
      fontFamily: {
        sans: ["Inter", "Helvetica", "Arial", "sans-serif"],
        mono: ["Roboto Mono", "monospace"],
      },
      borderRadius: { sm: "4px", md: "6px", lg: "10px", pill: "9999px" },
      // shadcn components (Card/Badge/Table) use the bare `border` utility,
      // which Tailwind's core theme otherwise defaults to gray-200 — point
      // it at design.md's border.default token instead.
      borderColor: {
        DEFAULT: "rgba(204,204,220,0.2)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
