import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [tailwindcss()],
  cacheDir: '.vite',
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // Backend port 8152 (see docs); end-to-end tests point this elsewhere with API_PROXY_TARGET.
      '/api': process.env.API_PROXY_TARGET || 'http://127.0.0.1:8152',
    },
    fs: {
      allow: ['..'],
    },
  },
})
