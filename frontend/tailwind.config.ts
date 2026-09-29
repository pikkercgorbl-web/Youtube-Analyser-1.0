import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        surface: {
          raised: "hsl(var(--surface-raised))",
          sunken: "hsl(var(--surface-sunken))",
        },
        status: {
          ok: "hsl(var(--status-ok))",
          warn: "hsl(var(--status-warn))",
          error: "hsl(var(--status-error))",
          unknown: "hsl(var(--status-unknown))",
        },
        lifecycle: {
          probation: "hsl(var(--lifecycle-probation))",
          active: "hsl(var(--lifecycle-active))",
          weak: "hsl(var(--lifecycle-weak))",
          archived: "hsl(var(--lifecycle-archived))",
        },
        evidence: {
          insufficient: "hsl(var(--evidence-insufficient))",
          early: "hsl(var(--evidence-early))",
          established: "hsl(var(--evidence-established))",
        },
        checkpoint: {
          due: "hsl(var(--checkpoint-due))",
          overdue: "hsl(var(--checkpoint-overdue))",
          pending: "hsl(var(--checkpoint-pending))",
          done: "hsl(var(--checkpoint-done))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "pulse-glow": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.7" },
        },
      },
      animation: {
        "pulse-glow": "pulse-glow 2s ease-in-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
