import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 正式编辑器构建：产物输出到 spug_web/public/native-ledger，
// CRA 构建（spug_web/package.json 的 build）会自动把 public/ 拷贝进
// build/，生产镜像与 dev server 均经 /native-ledger/index.html 访问。
// PDF 导出不依赖本地服务：编辑器打印预览只做分页 HTML 预览，
// 导出经消息桥由宿主页面调用后端正式接口（native-ledgers export/pdf）。
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "../public/native-ledger",
    emptyOutDir: true,
  },
  server: { port: 4173, strictPort: true, host: "127.0.0.1" },
});
