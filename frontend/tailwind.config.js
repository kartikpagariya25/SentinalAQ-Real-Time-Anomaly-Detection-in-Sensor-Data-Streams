export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: "#dc2626",
        branddark: "#b91c1c",
        brandpale: "#fef2f2",
        canvas: "#f4f5f7",
        surface: "#ffffff",
        ink: "#0f172a",
        muted: "#64748b",
        line: "#e5e7eb",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,0.04), 0 1px 3px rgba(15,23,42,0.06)",
      },
    },
  },
  plugins: [],
};
