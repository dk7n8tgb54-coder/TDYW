# 统一打印布局真机验收产物（2026-10-21）

## 背景

「设备管理 → 维护台账（Excel 路线）」网页与 PDF 排版统一改造的真实验收产物。
生成链路（全部真实路径，非 mock）：

- 后端服务层：`excel_print_layout.build_print_plan`（分页计划）→
  `excel_print_html.render_print_html`（统一打印 HTML）→
  `excel_browser_pdf_service`（独立 worker 子进程 + 无头 Chromium 1.64 /
  Chrome Headless Shell 156 打印）；
- 运行环境：tdyw-test 开发容器（`EXCEL_PDF_ENGINE=chromium`，
  `PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright`，中文字体 Noto Sans/Serif CJK）；
- 生成脚本：`quality/equipment_quality/print_unify_artifacts.py`（容器内对
  开发库走真实 HTTP：登录 → 上传模板 → 绑定 → 发布 → 创建台账 → 填值 →
  导出/预览），网页截图：`quality/e2e/tools/print_unify_capture.mjs`
  （真实 UI 登录 + 深链 + 填写/预览页签交互）。

## 两类代表模板

| case | 模板特征 | 验证点 |
|---|---|---|
| wide-landscape | 横向 A4、12 列较宽表、多级合并表头（A2:D2/E2:H2/I2:L2）、fitToWidth | 横向纸张交换宽高、fit 缩放、多级合并、填写值文本层可选 |
| long-portrait | 纵向 A4、85 行长表、底部大面积维护记录/维护人/日期合并区 | 纵向多页分页（2 页）、底部留白 ≥ 下边距、维护人日期在正文区内 |

## 产物清单

- `{case}-export.pdf` / `{case}-print.pdf`：导出与打印预览
  （同一生成服务；本环境两次独立生成字节数一致，缓存命中时逐字节一致）；
- `{case}-page-N.png`：预览 PDF 经 pdftoppm(80dpi) 渲染的页图
  （**即打印预览 iframe 中的内容**）；
- `{case}-plan.json`：版本详情 `print_plan`（网页分页参考线的唯一来源）；
- `{case}-web-fill-fitwidth.png` / `{case}-web-fill-original.png`：
  填写视图两种显示模式（transform 等比缩放，布局像素不随倍率变化）；
- `{case}-web-preview.png`：详情「打印预览」页签（反馈头"A4 210x297mm · N 页"
  来自 pypdf 读取真实产物；iframe 区域空白为 headless Chromium 不渲染内置
  PDF viewer 的截图限制，非功能缺陷——预览内容即 `{case}-page-N.png`，
  有头浏览器中正常显示）。

## 网页 vs PDF 对照结论（人工目检）

- wide-landscape：网页纸张卡片（A4 横向整页）与 PDF 第 1 页版式一致——
  标题合并、多级表头、12 列列宽比例、行高逐行对应；说明文案
  「纸张：A4 · 横向 · 共 1 页」由 print_plan 驱动；
- long-portrait：分页计划 2 页与 PDF 页数一致（page_breaks=[50]）；
  PDF 第 2 页末行文字（维护日期）距页底 ≥ 下边距 25.4mm（pdftotext -bbox
  量测 + 目检），底部无内容贴边；
- 未换行长文本（"更换风扇并清理滤网，巡检无其他异常"）按 Excel 语义向右
  溢出到空格显示，两端同一规则；
- 差异说明（已知且符合设计）：网页填写态绑定格内是输入控件（宽度 100%
  不溢出），打印态为文本按 Excel 溢出语义渲染；历史只读回放与打印一致。

## 第二轮修复（2026-10-21 用户实机反馈）

用户反馈：填写视图状态列偏左、表格与打印预览比例不一致。定位与修复：

1. `.el-fill-paper` 为 content-box，内联宽高被当"内容区宽"再叠加页边距
   padding → 纸张实际渲染 940×1269px（比 A4 大一圈）；修复为 border-box，
   内联宽高语义 = 纸张总尺寸，A4 卡片恒等于 794×1123px；
2. 表格未应用打印计划的 scale（fit_width<1 的模板，PDF 表格缩至可打印区
   而填写视图 100% 溢出纸张）；修复为 FillSheetArea 增加"打印缩放层"
   （transform: scale(plan.scale)，参考线偏移同步缩放），填写视图与 PDF
   的表格/纸张比例严格一致；
3. LayoutTable 表格补显式 width = 列宽和（fixed 布局 shrink-to-fit 不再受
   容器干扰，测量稳定）；
4. 填写控件（Select/Input/TextArea）文本对齐透传模板单元格 align——
   填写值/占位符与打印 PDF 的对齐逐格一致。

验证：`user-ledger-76-fill-after-fix.png`（自动转报机月维护记录表 v3，
scale=0.8374）：纸张 A4 正确、状态列"正常"居中、列宽视觉 216px 与 PDF
（258×0.8374）一致；jest 全量 1479 例、门禁 0 错 0 警通过。

### 第三轮（wrap 滚动条压住表格末行）

打印缩放层引入后，`LayoutTable` 外层 wrap 的内联 `overflow: auto` 使
表格（布局宽 775px）在缩放占位宽 649px 内出现横向滚动条并遮挡"日期"行；
填写纸张视图改为 `wrapOverflow="visible"`（表格溢出由打印缩放层 transform
与纸张语义处理，页面滚动由外层区域承担）。验证：已完成的
EL-WM-20261019-0004 历史回放
（`user-ledger-0004-fill-scrollbar-fixed.png`）：滚动条消失、末行"日期"
完整可见、三列比例与打印预览一致。

## 关联测试

- `apps/equipment_lifecycle/tests/stable_contract/test_excel_print_layout.py`
  （22 例：纸张/方向/边距/缩放/行分页/列块/page_order/打印区域/空白表）；
- `apps/equipment_lifecycle/tests/stable_contract/test_excel_browser_pdf.py`
  （11 例：真实 Chromium 纸张/方向/文本层/预览=导出/缓存失效/底部留白 bbox
  量测/多表；Chromium 缺失环境显式 NOT_RUN）；
- 设备全生命周期全量回归 659 例 + 前端全量 1479 例全绿（2026-10-21）。
