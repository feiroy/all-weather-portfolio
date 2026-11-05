import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时 npm run dev（5173）把 /api 转给 Python 接口（8600）；正式用 npm run build，由接口服务直接托管 dist/
export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 5173, proxy: { '/api': 'http://127.0.0.1:8600' } },
  build: { chunkSizeWarningLimit: 1200 },
})
