import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

/** Keep development and production on the same `/api` boundary. */
export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, '.', '');
  const backendTarget = environment.VITE_BACKEND_TARGET || 'http://127.0.0.1:8001';
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': backendTarget,
      },
    },
    preview: {
      port: 4173,
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            vitePreload: ['\0vite/preload-helper.js'],
            react: ['react', 'react-dom', 'react-router-dom'],
            antd: ['antd', '@ant-design/icons'],
            echarts: ['echarts'],
            openlayers: ['ol'],
          },
          onlyExplicitManualChunks: true,
        },
      },
    },
  };
});
