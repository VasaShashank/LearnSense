/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        taproot: {
          bg: '#090d16',
          surface: '#111827',
          panel: '#1f293d',
          border: '#2e3d59',
          cyan: '#06b6d4',
          emerald: '#10b981',
          amber: '#f59e0b',
          rose: '#f43f5e',
          violet: '#8b5cf6',
          accent: '#38bdf8',
        }
      },
      boxShadow: {
        'glow-cyan': '0 0 25px rgba(6, 182, 212, 0.4)',
        'glow-emerald': '0 0 25px rgba(16, 185, 129, 0.4)',
        'glow-amber': '0 0 25px rgba(245, 158, 11, 0.4)',
        'glow-rose': '0 0 25px rgba(244, 63, 94, 0.4)',
      },
      animation: {
        'pulse-glow': 'pulseGlow 2.5s infinite ease-in-out',
        'ripple': 'ripple 1.8s cubic-bezier(0, 0.2, 0.8, 1) infinite',
        'float': 'float 4s ease-in-out infinite',
      },
      keyframes: {
        pulseGlow: {
          '0%, 100%': { opacity: '0.9', transform: 'scale(1)' },
          '50%': { opacity: '1', transform: 'scale(1.05)' },
        },
        ripple: {
          '0%': { transform: 'scale(0.8)', opacity: '1' },
          '100%': { transform: 'scale(2.2)', opacity: '0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-6px)' },
        }
      }
    },
  },
  plugins: [],
}
