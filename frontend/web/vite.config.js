import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 默认端口 5173 与后端 .env 的 CORS_ORIGINS 一致；换端口要改自己电脑的 CORS_ORIGINS。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000' },
    port: 5173,
    strictPort: false,
  },
})
