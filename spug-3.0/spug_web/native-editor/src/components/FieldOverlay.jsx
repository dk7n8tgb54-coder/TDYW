import { useEffect, useRef } from "react";

function fitFontSize(input, max) {
  if (!input) return;
  let size = max;
  input.style.fontSize = `${size}px`;
  while (size > 11 && input.scrollWidth > input.clientWidth + 1) {
    size -= 1;
    input.style.fontSize = `${size}px`;
  }
}

function FieldControl({ binding, rect, value, active, onChange, onFocus }) {
  const inputRef = useRef(null);
  const isTextarea = binding.type === "textarea";
  const isStatus = binding.type === "status";
  const maxFont = isTextarea
    ? 13
    : Math.max(12, Math.min(16, rect.height * 0.38));

  useEffect(() => {
    if (!isTextarea && !isStatus) fitFontSize(inputRef.current, maxFont);
  }, [value, rect.width, rect.height, maxFont, isTextarea, isStatus]);

  const common = {
    ref: inputRef,
    value: value ?? "",
    onChange: (event) => onChange(binding.key, event.target.value),
    onFocus,
    "data-field-key": binding.key,
    "aria-label": binding.label,
    title: binding.label,
    spellCheck: false,
    className: `field-input${active ? " is-active" : ""}`,
    style: { fontSize: `${maxFont}px` },
  };

  if (isStatus) {
    const statusClass = value === "正常" ? " is-normal" : value === "不正常" ? " is-bad" : "";
    return (
      <div
        className={`field-box${active ? " is-active" : ""}`}
        style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
      >
        {active && <span className="field-caption">{binding.label}</span>}
        <select
          {...common}
          className={`field-input is-status${statusClass}${active ? " is-active" : ""}`}
          style={{ fontSize: "12px" }}
          value={value ?? ""}
          onChange={(event) => onChange(binding.key, event.target.value)}
        >
          <option value="">请选择</option>
          <option value="正常">正常</option>
          <option value="不正常">不正常</option>
        </select>
      </div>
    );
  }

  return (
    <div
      className={`field-box${active ? " is-active" : ""}`}
      style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
    >
      {active && <span className="field-caption">{binding.label}</span>}
      {isTextarea ? (
        <textarea
          {...common}
          onKeyDown={(event) => {
            if (event.key === "Escape") event.currentTarget.blur();
          }}
        />
      ) : (
        <input
          {...common}
          type="text"
          inputMode={binding.type === "number" ? "decimal" : undefined}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === "Escape") event.currentTarget.blur();
          }}
        />
      )}
    </div>
  );
}

export default function FieldOverlay({ bindings, values, rects, activeKey, onChange, onFocus }) {
  return (
    <div className="field-overlay" aria-label="台账填写层">
      {bindings.map((binding) => {
        const rect = rects[binding.key];
        if (!rect || rect.width < 8 || rect.height < 8) return null;
        return (
          <FieldControl
            key={binding.key}
            binding={binding}
            rect={rect}
            value={values[binding.key]}
            active={activeKey === binding.key}
            onChange={onChange}
            onFocus={() => onFocus(binding.key)}
          />
        );
      })}
    </div>
  );
}
