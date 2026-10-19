import { useState } from "react";
import { BINDING_TYPES, PAPER_PRESETS } from "../template";

function groupBindings(bindings) {
  const groups = new Map();
  for (const binding of bindings) {
    if (!groups.has(binding.section || "未分组")) groups.set(binding.section || "未分组", []);
    groups.get(binding.section || "未分组").push(binding);
  }
  return [...groups.entries()];
}

/**
 * 模板编辑侧栏：模板标题 / 纸张打印 / 字段绑定（单个 + 批量）。
 * 保存与发布动作在宿主页面工具栏（经消息桥收集全量状态），本面板
 * 只负责编辑面内容，不直接调用任何接口。
 */
export default function TemplatePanel({
  bindingCount,
  bindings,
  paper,
  title,
  onTitleChange,
  onApplyTitle,
  selectedRange,
  onAddBinding,
  onBatchBind,
  onRemoveBinding,
  onChangePaper,
  dirty,
}) {
  const [label, setLabel] = useState("");
  const [type, setType] = useState("text");
  const [required, setRequired] = useState(false);
  const [batchPrefix, setBatchPrefix] = useState("状态确认");
  const [batchType, setBatchType] = useState("status");
  const [query, setQuery] = useState("");
  const groups = groupBindings(bindings).filter(([, items]) =>
    !query || items.some((item) => `${item.label} ${item.range}`.toLowerCase().includes(query.toLowerCase())),
  );

  const submit = (event) => {
    event.preventDefault();
    if (!label.trim()) return;
    onAddBinding({ label: label.trim(), type, isRequired: required });
    setLabel("");
    setRequired(false);
  };

  return (
    <aside className="panel template-panel">
      <section className="panel-section">
        <div className="section-heading">
          <h2>模板信息</h2>
          <span className="pill">{dirty ? "有未保存修改" : "草稿已保存"}</span>
        </div>
        <label className="field-label" htmlFor="template-title">台账标题（写入 A1 合并格）</label>
        <div className="inline-control">
          <input
            id="template-title"
            value={title}
            onChange={(event) => onTitleChange(event.target.value)}
            placeholder="输入模板标题"
          />
          <button id="apply-title" className="button compact" onClick={onApplyTitle}>应用</button>
        </div>
        <p className="help-text">标题写入合并单元格 A1，正文与版式由 Univer 编辑器直接修改。</p>
      </section>

      <section className="panel-section">
        <h2>纸张与打印</h2>
        <div className="two-col">
          <label className="field-label">纸张
            <select
              id="template-paper-size"
              value={paper.size}
              onChange={(event) => onChangePaper({ size: event.target.value })}
            >
              {Object.entries(PAPER_PRESETS).map(([key, item]) => (
                <option key={key} value={key}>{item.label}</option>
              ))}
            </select>
          </label>
          <label className="field-label">方向
            <select
              id="template-paper-orientation"
              value={paper.orientation}
              onChange={(event) => onChangePaper({ orientation: event.target.value })}
            >
              <option value="portrait">纵向</option>
              <option value="landscape">横向</option>
            </select>
          </label>
        </div>
        <label className="check-label">
          <input
            type="checkbox"
            checked={paper.fitToWidth}
            onChange={(event) => onChangePaper({ fitToWidth: event.target.checked })}
          />
          超宽时自动适应页宽
        </label>
        <div className="margin-grid">
          {[["top", "上"], ["right", "右"], ["bottom", "下"], ["left", "左"]].map(([side, text]) => (
            <label key={side} className="field-label">
              {text}边距
              <input
                id={`template-margin-${side}`}
                type="number"
                min="4"
                max="40"
                value={paper.margins[side]}
                onChange={(event) => onChangePaper({
                  margins: { ...paper.margins, [side]: Math.max(4, Math.min(40, Number(event.target.value) || 4)) },
                })}
              />
            </label>
          ))}
        </div>
      </section>

      <section className="panel-section">
        <div className="section-heading">
          <h2>字段绑定 <span className="count">{bindingCount}</span></h2>
          <span className="pill light">选择单元格后绑定</span>
        </div>
        <div className="selection-readout">
          <span>当前选区</span>
          <code id="selected-range">{selectedRange || "尚未选择"}</code>
        </div>
        <form className="binding-form" onSubmit={submit}>
          <input
            id="binding-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="字段名称，例如：复测人"
          />
          <select id="binding-type" value={type} onChange={(event) => setType(event.target.value)}>
            {BINDING_TYPES.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <label className="check-label">
            <input
              id="binding-required"
              type="checkbox"
              checked={required}
              onChange={(event) => setRequired(event.target.checked)}
            />
            必填
          </label>
          <button id="add-binding" className="button primary compact" type="submit">绑定选区</button>
        </form>
        <p className="help-text">绑定只记录目标单元格，不重写 Univer 的网格、合并和尺寸数据；必填字段在"完成填写"时校验。</p>

        <div className="batch-bind-box">
          <div className="batch-bind-head">
            <strong>批量绑定</strong>
            <span>按选区拆分到每个单元格 / 合并区</span>
          </div>
          <div className="batch-bind-grid">
            <input
              id="batch-label-prefix"
              value={batchPrefix}
              onChange={(event) => setBatchPrefix(event.target.value)}
              placeholder="字段名前缀"
            />
            <select id="batch-binding-type" value={batchType} onChange={(event) => setBatchType(event.target.value)}>
              {BINDING_TYPES.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
          </div>
          <button
            id="batch-bind"
            className="button primary full"
            onClick={() => onBatchBind({ labelPrefix: batchPrefix.trim(), type: batchType })}
          >
            批量绑定当前选区
          </button>
          <p className="help-text">当前选区：{selectedRange || "未选择"}。已绑定单元格会自动跳过。</p>
        </div>
        <input
          className="search-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索字段或单元格"
          aria-label="搜索字段"
        />
        <div className="binding-list">
          {groups.map(([section, items]) => (
            <div key={section} className="binding-group">
              <h3>{section}</h3>
              {items.map((binding) => (
                <div key={binding.id} className="binding-row">
                  <div>
                    <strong>{binding.label}{binding.is_required ? "（必填）" : ""}</strong>
                    <span>{binding.range} · {binding.type}</span>
                  </div>
                  <button className="link-danger" onClick={() => onRemoveBinding(binding.id)}>移除</button>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
