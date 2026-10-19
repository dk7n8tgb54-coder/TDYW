function sectionGroups(bindings) {
  const groups = new Map();
  for (const binding of bindings) {
    if (!groups.has(binding.section || "未分组")) groups.set(binding.section || "未分组", []);
    groups.get(binding.section || "未分组").push(binding);
  }
  return [...groups.entries()];
}

/**
 * 填写侧栏：当前台账元信息与字段导航。
 * 保存/完成/导出动作在宿主页面工具栏（经消息桥收集填写值），本面板
 * 只负责编辑面内容与打印预览入口，不直接调用任何接口。
 */
export default function FillPanel({
  meta,
  bindings,
  values,
  activeField,
  onFocusField,
  onOpenPrint,
}) {
  const filled = bindings.filter((binding) => String(values[binding.key] ?? "").trim()).length;
  const groups = sectionGroups(bindings);

  return (
    <aside className="panel fill-panel">
      <section className="panel-section">
        <div className="section-heading">
          <h2>当前台账</h2>
          <span className="pill">{meta?.statusText || "草稿"}</span>
        </div>
        <div className="record-meta">
          <span>编号：{meta?.ledgerNo || "—"}</span>
          <span>模板 v{meta?.versionNo ?? "—"}</span>
        </div>
        <div className="record-meta">
          <span>执行日期：{meta?.executedDate || "—"}</span>
          <span>已填写 {filled} / {bindings.length} 字段</span>
        </div>
        <div className="action-row">
          <button id="open-print" className="button primary" onClick={onOpenPrint}>打印预览</button>
        </div>
        {!meta?.editable && (
          <p className="help-text">当前台账为{meta?.statusText || "历史"}状态，填写层只读。</p>
        )}
      </section>

      <section className="panel-section">
        <div className="section-heading">
          <h2>填写字段</h2>
          <span className="pill light">点击定位</span>
        </div>
        <p className="help-text">输入控件按单元格实际尺寸定位并随表格滚动。</p>
        <div className="field-nav">
          {groups.map(([section, items]) => (
            <div key={section} className="field-nav-group">
              <h3>{section}</h3>
              {items.map((binding) => (
                <button
                  key={binding.key}
                  id={`field-nav-${binding.key}`}
                  className={`field-nav-row${activeField === binding.key ? " is-active" : ""}`}
                  onClick={() => onFocusField(binding.key)}
                >
                  <span>{binding.label}{binding.is_required ? " *" : ""}</span>
                  <code>{binding.range}</code>
                </button>
              ))}
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
