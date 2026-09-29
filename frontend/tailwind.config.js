/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        display: ['"Space Grotesk"', '"Plus Jakarta Sans"', 'sans-serif'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      colors: {
        space: {
          950: '#05070D',
          900: '#080C14',
          850: '#0B1020',
          800: '#0E1422',
          750: '#111827',
          700: '#161F33',
          600: '#1E293B',
          500: '#334155',
        },
        universe: {
          cyan: '#00F0FF',
          blue: '#38BDF8',
          violet: '#8B5CF6',
          emerald: '#10B981',
          amber: '#F59E0B',
          rose: '#F43F5E',
          slate: '#8D99AA',
          muted: '#5A667A',
          text: '#F4F7FB',
        },
        taproot: {
          bg: '#05070D',
          surface: '#0E1422',
          panel: '#111827',
          border: 'rgba(255, 255, 255, 0.08)',
          cyan: '#00F0FF',
          emerald: '#10B981',
          amber: '#F59E0B',
          rose: '#F43F5E',
          violet: '#8B5CF6',
          accent: '#38BDF8',
        }
      },
      boxShadow: {
        'glow-cyan': '0 0 20px -2px rgba(0, 240, 255, 0.25)',
        'glow-emerald': '0 0 20px -2px rgba(16, 185, 129, 0.25)',
        'glow-amber': '0 0 20px -2px rgba(245, 158, 11, 0.25)',
        'glow-rose': '0 0 20px -2px rgba(244, 63, 94, 0.25)',
        'glow-violet': '0 0 20px -2px rgba(139, 92, 246, 0.25)',
        'subtle-panel': '0 12px 36px -8px rgba(0, 0, 0, 0.7), inset 0 1px 0 rgba(255, 255, 255, 0.06)',
      },
      animation: {
        'pulse-glow': 'pulseGlow 3s infinite ease-in-out',
        'subtle-drift': 'subtleDrift 8s ease-in-out infinite',
        'fade-in': 'fadeIn 0.35s cubic-bezier(0.16, 1, 0.3, 1)',
        'scale-in': 'scaleIn 0.35s cubic-bezier(0.16, 1, 0.3, 1)',
        'scanline': 'scanline 6s linear infinite',
      },
      keyframes: {
        pulseGlow: {
          '0%, 100%': { opacity: '0.9', transform: 'scale(1)' },
          '50%': { opacity: '1', transform: 'scale(1.02)' },
        },
        subtleDrift: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-4px)' },
        },
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.97)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        scanline: {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(1000%)' },
        }
      }
    },
  },
  plugins: [],
}
