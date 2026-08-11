import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteStaticCopy } from 'vite-plugin-static-copy';

// 将 Cesium Worker、控件和静态资源复制到稳定公共路径。
export default defineConfig({
  define: {
    CESIUM_BASE_URL: JSON.stringify('/cesiumStatic'),
  },
  plugins: [
    react(),
    viteStaticCopy({
      targets: [
        { src: 'node_modules/cesium/Build/Cesium/Workers', dest: 'cesiumStatic' },
        { src: 'node_modules/cesium/Build/Cesium/ThirdParty', dest: 'cesiumStatic' },
        { src: 'node_modules/cesium/Build/Cesium/Assets', dest: 'cesiumStatic' },
        { src: 'node_modules/cesium/Build/Cesium/Widgets', dest: 'cesiumStatic' },
      ],
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      // 本地开发使用同源 `/api`，避免页面持有环境专属后端地址。
      '/api': 'http://127.0.0.1:8001',
    },
  },
  preview: {
    port: 4173,
  },
  build: {
    rollupOptions: {
      output: {
        // 将稳定第三方库拆分为可长期缓存的独立分块，降低业务入口包体。
        manualChunks: {
          vitePreload: ['\0vite/preload-helper.js'],
          react: ['react', 'react-dom', 'react-router-dom'],
          antd: ['antd', '@ant-design/icons'],
          echarts: ['echarts'],
          cesium: ['cesium'],
        },
        // 只把显式包入口放入手工分块，防止 Vite 预加载辅助模块被卷入 Cesium。
        onlyExplicitManualChunks: true,
      },
    },
  },
});
