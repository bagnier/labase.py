/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["app/**/templates/**/*.html"],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui'] },
      colors: { sidebar: '#0f1117' },
    }
  },
  plugins: [],
}
