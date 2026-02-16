/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#1e3a5f',
        'primary-light': '#2c5282',
        accent: '#e8942e',
        'accent-hover': '#d4841f',
        success: '#22c55e',
        warning: '#f59e0b',
        error: '#ef4444',
        bg: '#f1f5f9',
        card: '#ffffff',
        'text-main': '#1e293b',
        'text-light': '#64748b',
        border: '#e2e8f0',
        'edit-highlight': '#fef3c7',
        'pdf-bg': '#1a1a2e',
        'pdf-toolbar': '#16162a',
      },
    },
  },
  plugins: [],
}
