import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, theme } from 'antd';
import { RouterProvider } from 'react-router-dom';
import { appRouter } from './router';
import './styles.css';

// 统一注入 Ant Design 暗色主题，确保所有组件沿用平台视觉令牌。
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#2fe6d6',
          colorInfo: '#37a7ff',
          colorBgBase: '#06101c',
          colorTextBase: '#eaf8ff',
          borderRadius: 8,
          fontFamily:
            'Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
        },
      }}
    >
      <RouterProvider router={appRouter} />
    </ConfigProvider>
  </React.StrictMode>,
);
