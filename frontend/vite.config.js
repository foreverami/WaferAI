import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // 개발 중에는 Vite(5173)와 FastAPI(8000)가 다른 포트라 쿠키가 오가지 않는다.
    // 프록시로 같은 출처처럼 보이게 한다. 운영에서는 Nginx 가 같은 일을 한다.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/healthz': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
