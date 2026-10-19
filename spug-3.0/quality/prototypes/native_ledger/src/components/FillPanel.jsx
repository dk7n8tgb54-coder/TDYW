function sectionGroups(bindings) {
  const groups = new Map();
  for (const binding of bindings) {
    if (!groups.has(binding.section)) groups.set(binding.section, []);
    groups.get(binding.section).push(binding);
  }
  return [...groups.entries()];
}

export default function FillPanel({
  session,
  records,
  versions,
  bindings,
  activeField,
  onOpenRecord,
  onNewRecord,
  onSaveRecord,
  onCodeChange,
  onTitleChange,
  onFocusField,
  onOpenPrint,
  saving,
  onReset,
  onClear,
}) {
  if (!session) {
    return (
      <aside className="panel fill-panel">
        <section className="panel-section">
          <h2>填写台账</h2>
          <p className="help-text">请先打开一条台账，或新建台账。</p>
          <button className="button primary" onClick={onNewRecord}>新建台账</button>
        </section>
      </aside>
    );
  }

  const version = versions.find((item) => item.id === session.versionId);
  const filled = bindings.filter((binding) => String(session.values[binding.key] ?? "").trim()).length;
  const groups = sectionGroups(bindings);

  return (
    <aside className="panel fill-panel">
      <section className="panel-section">
        <div className="section-heading">
          <h2>当前台账</h2>
          <span className="pill">{session.saved ? "已保存" : "未保存"}</span>
        </div>
        <label className="field-label">台账编号
          <input id="record-code" value={session.code} onChange={(event) => onCodeChange(event.target.value)} />
        </label>
        <label className="field-label">台账名称
          <input id="record-title" value={session.title} onChange={(event) => onTitleChange(event.target.value)} />
        </label>
        <div className="record-meta">
          <span>模板 {version?.label || "未知版本"}</span>
          <span>已填写 {filled} / {bindings.length} 字段</span>
        </div>
        <div className="action-row">
          <button id="save-record" className="button primary" onClick={onSaveRecord} disabled={saving}>
            {saving ? "保存中…" : "保存台账"}
          </button>
          <button id="open-print" className="button ghost" onClick={onOpenPrint}>打印预览</button>
        </div>
        <button id="new-record" className="button subtle full" onClick={onNewRecord}>＋ 新建空白台账</button>
      </section>

      <section className="panel-section">
        <h2>已保存台账</h2>
        <div className="record-list">
          {records.map((record) => {
            const label = versions.find((item) => item.id === record.versionId)?.label || "未知版本";
            return (
              <button
                key={record.id}
                className={`record-row${record.id === session.recordId ? " is-active" : ""}`}
                data-record-id={record.id}
                onClick={() => onOpenRecord(record.id)}
              >
                <span className="record-code">{record.code}</span>
                <strong>{record.title}</strong>
                <span>{record.status} · {label} · {new Date(record.updatedAt).toLocaleDateString("zh-CN")}</span>
              </button>
            );
          })}
          {records.length === 0 && <p className="help-text">暂无台账记录。</p>}
        </div>
      </section>

      <section className="panel-section">
        <div className="section-heading">
          <h2>填写字段</h2>
          <span className="pill light">点击定位</span>
        </div>
        <p className="help-text">输入控件按单元格实际尺寸定位；姓名框自动适配 88px 行高。</p>
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
                  <span>{binding.label}</span>
                  <code>{binding.range}</code>
                </button>
              ))}
            </div>
          ))}
        </div>
      </section>

      <section className="panel-section danger-zone">
        <h2>样板数据</h2>
        <div className="action-row">
          <button className="button ghost" onClick={onReset}>恢复示例</button>
          <button className="button danger" onClick={onClear}>清空样板数据</button>
        </div>
      </section>
    </aside>
  );
}
