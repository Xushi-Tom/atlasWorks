# AtlasWorks Frontend

当前前端已切换为 `Vue 3 + Vite` 工程，构建产物会复制到 Flask 容器的 `/app/static`。

## 现状

- Vue 负责页面壳层、导航状态、页面状态、数据加载与工具交互。
- 当前活跃 UI 已不再依赖 legacy HTML 模板或 legacy runtime。
- 后端继续只提供 `/api/*` 接口与静态构建产物分发。

## 目录

- `src/App.vue`: 应用主壳与页面切换。
- `src/components/AppHeader.vue`: 顶部栏。
- `src/components/AppSidebar.vue`: 左侧导航与折叠状态。
- `src/components/AppToastStack.vue`: 全局提示。
- `src/views/`: 各业务页面组件。
- `src/services/api.js`: 前端 API 访问层。

## 迁移建议

后续建议继续沿产品化方向推进：

1. 把地图/地形切片页继续拆成更细的表单子组件。
2. 为任务详情、文件详情补上 Vue 弹窗与抽屉。
3. 引入更明确的前端状态层，统一缓存当前浏览路径、筛选条件和最近操作。
