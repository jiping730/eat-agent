/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        cream: 'rgb(var(--cream) / <alpha-value>)',
        paper: 'rgb(var(--paper) / <alpha-value>)',
        ink: 'rgb(var(--ink) / <alpha-value>)',
        sage: 'rgb(var(--sage) / <alpha-value>)',
        mint: 'rgb(var(--mint) / <alpha-value>)',
        apricot: 'rgb(var(--apricot) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['"Noto Sans SC"', '"PingFang SC"', '"Microsoft YaHei"', 'sans-serif'],
        display: ['"Noto Serif SC"', '"Songti SC"', 'serif'],
      },
      borderRadius: { card: '16px', control: '10px' },
      boxShadow: { soft: 'var(--shadow-soft)', lift: 'var(--shadow-lift)' },
    },
  },
  plugins: [],
};
