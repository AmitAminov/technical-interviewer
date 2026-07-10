/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter Variable', 'Inter', 'Segoe UI', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      keyframes: {
        slideIn: {
          '0%': { opacity: '0', transform: 'translateY(14px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        sway: {
          '0%, 100%': { transform: 'translateY(0px) rotate(0deg)' },
          '50%': { transform: 'translateY(4px) rotate(0.6deg)' },
        },
        pulseRing: {
          '0%': { transform: 'scale(1)', opacity: '0.55' },
          '100%': { transform: 'scale(1.22)', opacity: '0' },
        },
        typingDot: {
          '0%, 80%, 100%': { opacity: '0.25' },
          '40%': { opacity: '1' },
        },
        // Subtle "breathing" for the photorealistic talking portrait.
        breathe: {
          '0%, 100%': { transform: 'scale(1)' },
          '50%': { transform: 'scale(1.012)' },
        },
      },
      animation: {
        'slide-in': 'slideIn 0.3s ease-out both',
        'fade-in': 'fadeIn 0.25s ease-out both',
        sway: 'sway 5.5s ease-in-out infinite',
        'pulse-ring': 'pulseRing 1.5s ease-out infinite',
        'typing-dot': 'typingDot 1.2s infinite',
        breathe: 'breathe 5.5s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
