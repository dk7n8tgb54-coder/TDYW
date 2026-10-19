# 原生维护台账独立样板（Univer POC）

这是 `quality/prototypes/native_ledger/` 下的**独立验证样板**，不接入正式菜单、路由、
API、权限或数据库。所有模板、字段绑定、版本和台账记录只保存在浏览器 `localStorage`。

## 运行

```powershell
cd E:\TDYW\spug-3.0\quality\prototypes\native_ledger
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:4173/`。

- Node.js：20.18.0
- 电子表格引擎：`@univerjs/presets` / `@univerjs/preset-sheets-core` **1.1.0**（Apache-2.0）
- PDF：Chromium（Playwright）打印真实分页 HTML，不依赖 Univer Pro 打印插件
- 本地缓存目录 `.npm-cache/`、`.pydeps/`、`node_modules/`、`dist/` 已被 `.gitignore` 忽略

## 功能入口

| 功能 | 位置 |
|---|---|
| 模板编辑、单字段绑定、**批量绑定**、纸张设置、发布版本 | “模板制作”页签 |
| 文本/数值/日期/多行文本/**正常-不正常二选一** | 单字段或批量绑定类型 |
| 台账填写、保存、重开、恢复/清空数据 | “填写台账”页签 |
| 填写层随表格上下滚动同步移动 | “填写台账”页签 |
| A4/A3、横竖、页边距、打印预览、PDF 导出 | “填写台账” → “打印预览” |

## 可重复验证

```powershell
cd E:\TDYW\spug-3.0\quality\prototypes\native_ledger
node tools/e2e_full.mjs
```

脚本会真实操作浏览器完成：改标题 → 选中 E5 新增绑定 → 发布 v2 → 新建台账
→ 填写 34 个字段 → 保存 → 刷新重开 → 核对值 → 导出 A4/A3/A4 纵向 PDF
→ 桌面和 900px 窄屏截图 → 清空并恢复示例。

批量绑定、状态字段和滚动跟随：

```powershell
node tools/e2e_batch_status.mjs
```

脚本会拖选 `M13:M16`，一次批量绑定 4 个“正常/不正常”字段，保存重开，
并用鼠标滚轮滚动后核对输入层坐标是否跟随。

PDF 反查：

```powershell
python tools/verify_pdfs.py
python tools/render_pdf.py <pdf> <输出目录> <文件名前缀>
```

PDF 检查使用本地 `.pydeps` 中的 PyMuPDF，运行时需把 `.pydeps` 加入 `sys.path`；
两个脚本已内置该路径。

## 边界与未实现能力

- 没有 Excel 导入/导出；Univer 开源核心 preset 不含 Excel 导入导出，Pro 商业包未安装、未使用。
- 打印/PDF 是自建分页 HTML + Chromium 实际打印，不是 Univer 原生打印能力。
- 版本能力只做到“快照版本 + 台账保留版本号”，没有版本差异、回滚、审计。
- 没有“一键生成台账”或批量生成。
- 没有生产 API、租户、权限、附件、审批流接入。
