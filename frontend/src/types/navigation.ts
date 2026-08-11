import type { ReactNode } from 'react';

// 描述侧边导航与功能占位页共用的稳定元数据。
export interface NavigationItem {
  key: string;
  label: string;
  path: string;
  icon: ReactNode;
  eyebrow: string;
  description: string;
}
