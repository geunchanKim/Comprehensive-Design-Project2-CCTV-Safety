import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // 백엔드에 CORS 설정이 없어서 개발 중에는 프록시로 우회한다
  const backend = env.VITE_BACKEND_URL || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: backend,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
