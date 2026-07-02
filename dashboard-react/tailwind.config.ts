import type { Config } from 'tailwindcss'

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // ALPESTATE — CSS-var-aware tokens
        // Layout (static, maps to new palette)
        alpine: {
          void:    'oklch(0.97 0 0)',
          deep:    'oklch(0.975 0 0)',
          base:    'oklch(0.945 0 0)',
          surface: 'oklch(0.975 0 0)',
          card:    '#ffffff',
          hover:   'oklch(0.96 0 0)',
          border:  'oklch(0.905 0 0)',
          muted:   'oklch(0.85 0 0)',
          line:    'oklch(0.78 0 0)',
        },
        // Accent
        ice: {
          DEFAULT: 'oklch(0.54 0.175 234)',
          bright:  'oklch(0.54 0.175 234)',
          pale:    'oklch(0.88 0.06 234)',
          deep:    'oklch(0.44 0.18 234)',
          glow:    'oklch(0.40 0.17 234)',
        },
        // Semantic
        glow: {
          green:  'oklch(0.52 0.155 152)',
          amber:  'oklch(0.68 0.155 70)',
          red:    'oklch(0.56 0.195 27)',
          violet: 'oklch(0.52 0.18 300)',
        },
        alpenglow: 'oklch(0.64 0.17 40)',
        accent:    'oklch(0.72 0.095 72)',
      },
      fontFamily: {
        display: ['Schibsted Grotesk', 'system-ui', 'sans-serif'],
        body:    ['Schibsted Grotesk', 'system-ui', 'sans-serif'],
        mono:    ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.65rem', { lineHeight: '1rem' }],
        'xs':  ['0.72rem', { lineHeight: '1.1rem' }],
      },
      borderRadius: {
        'xs':  '6px',
        'sm':  '8px',
        DEFAULT: '8px',
        'md': '12px',
        'lg': '16px',
        'xl': '20px',
        '2xl': '24px',
      },
      boxShadow: {
        'sm':         '0 1px 3px oklch(0 0 0 / 0.05), 0 8px 24px oklch(0 0 0 / 0.04)',
        'md':         '0 2px 8px oklch(0 0 0 / 0.07), 0 20px 48px oklch(0 0 0 / 0.08)',
        'glow-accent':'0 4px 16px oklch(0.72 0.095 72 / 0.35)',
        'glow-green': '0 2px 8px oklch(0.52 0.155 152 / 0.35)',
        'glow-blue':  '0 2px 8px oklch(0.54 0.175 234 / 0.35)',
        'glow-red':   '0 2px 8px oklch(0.56 0.195 27 / 0.35)',
        'card':       '0 1px 3px oklch(0 0 0 / 0.05), 0 4px 16px oklch(0 0 0 / 0.04)',
        'card-hover': '0 2px 8px oklch(0 0 0 / 0.07), 0 20px 48px oklch(0 0 0 / 0.08)',
      },
      animation: {
        'fade-in':  'fadeIn 0.15s ease-out',
        'slide-up': 'slideUp 0.2s cubic-bezier(0.16,1,0.3,1)',
        'shimmer':  'shimmer 1.5s ease-in-out infinite',
      },
    },
  },
  plugins: [],
} satisfies Config
