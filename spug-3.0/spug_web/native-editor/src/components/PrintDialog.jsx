import React from "react";
import { PAPER_PRESETS } from "../template";

const MARGIN_FIELDS = [
  ["top", "上"],
  ["right", "右"],
  ["bottom", "下"],
  ["left", "左"],
];

/**
 * 打印预览弹窗（填写模式）：纸张/方向/边距实时调整 + 分页预览。
 * 导出经消息桥请求宿主页面（宿主先保存未提交修改，再调用后端正式
 * 导出接口）；"浏览器打印"仍为本 iframe 本地打印能力。
 * locked=true（填写模式）：纸张与打印设置来自台账创建时固定的发布版本，
 * 只读展示；调整打印设置应回到模板编辑并发布新版本。
 */
export default function PrintDialog({
  doc,
  paper,
  locked = false,
  onChangePaper,
  onClose,
  onExport,
  exporting,
  iframeRef,
}) {
  if (!doc) return null;
  const setMargin = (side, raw) => {
    const value = Math.max(4, Math.min(40, Number(raw) || 0));
    onChangePaper({ margins: { ...paper.margins, [side]: value } });
  };

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="print-dialog" role="dialog" aria-modal="true" aria-label="打印预览">
        <header className="print-dialog-head">
          <div>
            <h2>打印预览与 PDF</h2>
            <p>预览使用与服务端导出一致的分页规范；导出前请先保存填写内容。</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭打印预览">×</button>
        </header>
        <div className="print-toolbar">
          {locked ? (
            <div className="print-meta" style={{ padding: 0 }}>
              <span>纸张 {paper.size} · {paper.orientation === "landscape" ? "横向" : "纵向"}</span>
              <span>页边距 {paper.margins.top}/{paper.margins.right}/{paper.margins.bottom}/{paper.margins.left} mm</span>
              <span>打印设置取自台账引用的发布版本，如需调整请在模板编辑中发布新版本</span>
            </div>
          ) : (
            <React.Fragment>
              <label>
                纸张
                <select id="paper-size" value={paper.size} onChange={(e) => onChangePaper({ size: e.target.value })}>
                  {Object.entries(PAPER_PRESETS).map(([key, item]) => (
                    <option key={key} value={key}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label>
                方向
                <select id="paper-orientation" value={paper.orientation} onChange={(e) => onChangePaper({ orientation: e.target.value })}>
                  <option value="portrait">纵向</option>
                  <option value="landscape">横向</option>
                </select>
              </label>
              <label className="check-label">
                <input
                  id="fit-to-width"
                  type="checkbox"
                  checked={paper.fitToWidth}
                  onChange={(e) => onChangePaper({ fitToWidth: e.target.checked })}
                />
                适应页宽
              </label>
              <div className="margin-group" aria-label="页边距（毫米）">
                {MARGIN_FIELDS.map(([side, label]) => (
                  <label key={side}>
                    {label}
                    <input
                      className="margin-input"
                      id={`margin-${side}`}
                      type="number"
                      min="4"
                      max="40"
                      step="1"
                      value={paper.margins[side]}
                      onChange={(e) => setMargin(side, e.target.value)}
                    />
                  </label>
                ))}
                <span className="unit">mm</span>
              </div>
            </React.Fragment>
          )}
          <div className="print-actions">
            <button className="button ghost" onClick={() => iframeRef.current?.contentWindow?.print()}>
              浏览器打印
            </button>
            <button id="export-pdf" className="button primary" onClick={onExport} disabled={exporting}>
              {exporting ? "正在生成 PDF…" : "导出 PDF"}
            </button>
          </div>
        </div>
        <div className="print-meta">
          <span>{doc.pageCount} 页</span>
          <span>缩放 {(doc.scale * 100).toFixed(0)}%</span>
          <span>表格宽度 {Math.round(doc.rawWidth)}px / 可打印 {Math.round(doc.contentWidth)}px</span>
          <span>合并格跨页 {doc.crossPageMerges.length} 处</span>
          <span>页边距 {paper.margins.top}/{paper.margins.right}/{paper.margins.bottom}/{paper.margins.left} mm</span>
        </div>
        {doc.warnings.length > 0 && (
          <ul className="print-warnings">
            {doc.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        )}
        <div className="print-preview-wrap">
          <iframe ref={iframeRef} title="打印分页预览" srcDoc={doc.html} />
        </div>
      </section>
    </div>
  );
}
