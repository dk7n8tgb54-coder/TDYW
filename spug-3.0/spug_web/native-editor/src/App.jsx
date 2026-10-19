import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createLedgerUniver, loadSnapshot } from "./univer";
import { EDITOR_SOURCE, MSG, listenHost, postToHost } from "./bridge";
import {
  DEFAULT_PAPER,
  buildEmptyValues,
  buildNewDraft,
  clone,
  normalizePaper,
} from "./template";
import { renderPrintDocument } from "./print";
import { collectBatchBindings } from "./bindings";
import { readViewportScroll } from "./scroll";
import TemplatePanel from "./components/TemplatePanel";
import FillPanel from "./components/FillPanel";
import PrintDialog from "./components/PrintDialog";
import FieldOverlay from "./components/FieldOverlay";

const SHEET_ID = "ledger";

function titleOf(snapshot) {
  return String(snapshot?.sheets?.[SHEET_ID]?.cellData?.[0]?.[0]?.v || "");
}

function previewZoomFor(paper) {
  const dims = { A4: { width: 210, height: 297 }, A3: { width: 297, height: 420 } }[paper.size];
  const widthMm = paper.orientation === "landscape" ? dims.height : dims.width;
  const widthPx = widthMm * (96 / 25.4);
  const available = Math.max(420, window.innerWidth - 120);
  return Math.max(0.35, Math.min(0.95, available / widthPx));
}

function sameRects(a, b) {
  const ak = Object.keys(a);
  const bk = Object.keys(b);
  if (ak.length !== bk.length) return false;
  return ak.every((key) => {
    const x = a[key];
    const y = b[key];
    return y && x.left === y.left && x.top === y.top && x.width === y.width && x.height === y.height;
  });
}

/** 编辑器组件：由宿主经消息桥驱动（nl-init 注入数据），自身不调用任何接口。 */
export default function App() {
  const [phase, setPhase] = useState("waiting"); // waiting | template | fill
  const [draft, setDraftState] = useState(null);   // template 模式：{snapshot, bindings, paper}
  const [ledger, setLedger] = useState(null);      // fill 模式：{snapshot, bindings, paper, values, meta}
  const [dirty, setDirty] = useState(false);
  const [title, setTitle] = useState("");
  const [selectedRange, setSelectedRange] = useState("");
  const [activeField, setActiveField] = useState(null);
  const [rects, setRects] = useState({});
  const [engineReady, setEngineReady] = useState(0);
  const [editorLoading, setEditorLoading] = useState(false);
  const [printOpen, setPrintOpen] = useState(false);
  const [previewZoom, setPreviewZoom] = useState(0.8);
  const [exporting, setExporting] = useState(false);

  const hostRef = useRef(null);
  const stageRef = useRef(null);
  const apiRef = useRef(null);
  const univerRef = useRef(null);
  const workbookRef = useRef(null);
  const worksheetRef = useRef(null);
  const currentIdRef = useRef(null);
  const iframeRef = useRef(null);
  const draftRef = useRef(null);
  const ledgerRef = useRef(null);
  const dirtyRef = useRef(false);
  const valuesRef = useRef({});

  const setDraft = useCallback((next) => {
    draftRef.current = next;
    setDraftState(next);
    setTitle(titleOf(next?.snapshot));
  }, []);

  const setLedgerData = useCallback((next) => {
    ledgerRef.current = next;
    valuesRef.current = { ...(next?.values || {}) };
    setLedger(next);
  }, []);

  const markDirty = useCallback(() => {
    dirtyRef.current = true;
    setDirty(true);
  }, []);

  const clearDirty = useCallback(() => {
    dirtyRef.current = false;
    setDirty(false);
  }, []);

  const notifyLocal = useCallback((text) => {
    // 本地轻提示：编辑器内操作反馈（保存结果等由宿主提示）
    setToast({ text, type: "ok" });
  }, []);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  // ==================== 引擎生命周期 ====================
  useEffect(() => {
    if (phase === "waiting" || !hostRef.current) return undefined;
    const host = hostRef.current;
    host.innerHTML = "";
    const { univer, univerAPI } = createLedgerUniver("univer-host");
    univerRef.current = univer;
    apiRef.current = univerAPI;
    setEngineReady((value) => value + 1);
    return () => {
      window.setTimeout(() => {
        try {
          univer.dispose();
        } catch {
          // Disposal is best effort during a hard reset.
        }
      }, 0);
      apiRef.current = null;
      univerRef.current = null;
      workbookRef.current = null;
      worksheetRef.current = null;
      currentIdRef.current = null;
      setEngineReady(0);
    };
  }, [phase]);

  // ==================== 快照装载（模板/填写共用） ====================
  useEffect(() => {
    if (!engineReady || !apiRef.current) return;
    let snapshot;
    let effectiveBindings;
    let values = {};
    if (phase === "fill" && ledgerRef.current) {
      snapshot = clone(ledgerRef.current.snapshot);
      effectiveBindings = ledgerRef.current.bindings;
      values = ledgerRef.current.values || {};
    } else if (phase === "template" && draftRef.current) {
      snapshot = clone(draftRef.current.snapshot);
      effectiveBindings = draftRef.current.bindings;
    } else {
      return;
    }
    snapshot.id = `native-ledger-${Date.now()}`;
    const hostWidth = hostRef.current?.clientWidth || 900;
    const hostHeight = hostRef.current?.clientHeight || 800;
    const zoom = phase === "fill"
      ? Math.max(0.36, Math.min(0.8, hostWidth / 1408, (hostHeight - 12) / 1132))
      : Math.max(0.45, Math.min(0.8, hostWidth / 1320));
    setEditorLoading(true);
    const loaded = loadSnapshot(apiRef.current, currentIdRef.current, snapshot, zoom);
    currentIdRef.current = loaded.id;
    workbookRef.current = loaded.fWorkbook;
    worksheetRef.current = loaded.fWorksheet;
    setActiveField(null);
    setRects({});
    attachDirtyTracker(apiRef.current, markDirty);

    if (phase === "fill") {
      window.setTimeout(() => {
        for (const binding of effectiveBindings) {
          try {
            loaded.fWorksheet.getRange(binding.range).setValue(values[binding.key] ?? "");
          } catch {
            // 失效绑定在绑定面板可见，装载不中断
          }
        }
        if (!ledgerRef.current?.meta?.editable) {
          loaded.fWorksheet.getWorksheetPermission().setReadOnly().catch(() => {});
        }
        setEditorLoading(false);
        window.setTimeout(() => {
          if (worksheetRef.current) {
            for (const binding of effectiveBindings) {
              try {
                worksheetRef.current.getRange(binding.range).getCellRect();
              } catch {
                // Force layout reads; individual failures are ignored.
              }
            }
          }
        }, 60);
      }, 120);
    } else {
      window.setTimeout(() => setEditorLoading(false), 300);
    }
  }, [engineReady, phase, ledger?.meta?.loadKey, draft?.loadKey, markDirty, ledger, draft]);

  // 选区轮询（模板模式绑定面板显示当前选区）
  useEffect(() => {
    if (phase !== "template" || !engineReady) return undefined;
    const timer = window.setInterval(() => {
      try {
        const ranges = worksheetRef.current?.getSelection()?.getActiveRangeList() || [];
        if (ranges.length) {
          const text = ranges.map((range) => range.getA1Notation()).join("、");
          setSelectedRange((previous) => (previous === text ? previous : text));
        }
      } catch {
        // Selection can be unavailable while the canvas is attaching.
      }
    }, 350);
    return () => window.clearInterval(timer);
  }, [phase, engineReady]);

  // ==================== 填写层定位（随滚动同步） ====================
  const bindings = phase === "fill"
    ? (ledger?.bindings || [])
    : (draft?.bindings || []);
  const paper = phase === "fill"
    ? normalizePaper(ledger?.paper)
    : normalizePaper(draft?.paper);

  const updateRects = useCallback(() => {
    if (phase !== "fill" || !worksheetRef.current || !stageRef.current) return;
    const stage = stageRef.current.getBoundingClientRect();
    const canvases = [...stageRef.current.querySelectorAll("canvas")]
      .map((canvas) => ({ canvas, rect: canvas.getBoundingClientRect() }))
      .filter((item) => item.rect.width > 300 && item.rect.height > 200);
    if (!canvases.length) return;
    const grid = canvases[canvases.length - 1].rect;
    const zoom = worksheetRef.current.getZoom?.() || 1;
    const scroll = readViewportScroll(worksheetRef.current);
    const originX = grid.left - stage.left;
    const originY = grid.top - stage.top;
    const skeleton = worksheetRef.current.getSkeleton?.();
    // 冻结区高度按当前快照实际冻结行数取值（rowHeightAccumulation 为累计
    // 高度数组，下标 ySplit-1 = 冻结行总高）；样板冻结 4 行时下标恰为 3，
    // 泛化到任意模板后不能硬编码（否则冻结行下方的前几格被误过滤）。
    const fillSnapshot = ledgerRef.current?.snapshot;
    const fillSheetId = fillSnapshot?.sheetOrder?.[0];
    const freezeRows = Number(
      fillSnapshot?.sheets?.[fillSheetId]?.freeze?.ySplit) || 0;
    const frozenAccum = freezeRows > 0
      ? (skeleton?.rowHeightAccumulation?.[freezeRows - 1] || 0)
      : 0;
    const frozenHeight = frozenAccum
      + (skeleton?.columnHeaderHeightAndMarginTop || 0);
    const mainTop = Math.max(0, originY + frozenHeight * zoom);
    const next = {};
    for (const binding of bindings) {
      try {
        const cell = worksheetRef.current.getRange(binding.range).getCell();
        const box = cell.mergeInfo || cell;
        const width = (box.endX - box.startX) * zoom;
        const height = (box.endY - box.startY) * zoom;
        const left = originX + (box.startX - scroll.x) * zoom;
        const top = originY + (box.startY - scroll.y) * zoom;
        if (
          width > 4 && height > 4 &&
          left + width > 0 && top + height > mainTop &&
          left < stage.width && top < stage.height
        ) {
          next[binding.key] = { left, top, width, height };
        }
      } catch {
        // Ignore cells that cannot be measured yet.
      }
    }
    setRects((previous) => (sameRects(previous, next) ? previous : next));
  }, [phase, bindings]);

  useEffect(() => {
    if (phase !== "fill" || !engineReady) return undefined;
    const body = stageRef.current;
    const schedule = [40, 250, 700, 1300].map((delay) => window.setTimeout(updateRects, delay));
    const interval = window.setInterval(updateRects, 80);
    const onWheel = () => {
      window.setTimeout(updateRects, 0);
      window.setTimeout(updateRects, 80);
      window.setTimeout(updateRects, 180);
    };
    window.addEventListener("resize", updateRects);
    body?.addEventListener("scroll", updateRects, true);
    body?.addEventListener("wheel", onWheel, { passive: true });
    return () => {
      schedule.forEach((timer) => window.clearTimeout(timer));
      window.clearInterval(interval);
      window.removeEventListener("resize", updateRects);
      body?.removeEventListener("scroll", updateRects, true);
      body?.removeEventListener("wheel", onWheel);
    };
  }, [phase, engineReady, updateRects, ledger?.meta?.loadKey]);

  useEffect(() => {
    if (!printOpen) return undefined;
    const update = () => setPreviewZoom(previewZoomFor(paper));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [printOpen, paper.size, paper.orientation]);

  // ==================== 消息桥：初始化与收集 ====================
  const collectState = useCallback(() => {
    const snapshot = workbookRef.current ? clone(workbookRef.current.save()) : null;
    if (phase === "fill") {
      return {
        snapshot: ledgerRef.current?.snapshot || {},
        bindings: ledgerRef.current?.bindings || [],
        paper: normalizePaper(ledgerRef.current?.paper),
        values: { ...valuesRef.current },
        dirty: dirtyRef.current,
      };
    }
    const base = draftRef.current || buildNewDraft();
    return {
      snapshot: snapshot || clone(base.snapshot),
      bindings: base.bindings,
      paper: base.paper,
      values: {},
      dirty: dirtyRef.current,
    };
  }, [phase]);

  // 消息监听只挂载一次：READY 仅在挂载时发送一次。切勿把 INIT 会重建的
  // 对象（draft/ledger/bindings）放进依赖——否则 READY→INIT→新引用→重跑
  // effect→再发 READY 形成 READY/INIT 无限循环，Univer 引擎每轮重建
  // （表现为"正在加载表格引擎"持续闪烁）。collectState 随 phase 变化，
  // 经 ref 取最新值。
  const collectStateRef = useRef(collectState);
  collectStateRef.current = collectState;
  const didPostReadyRef = useRef(false);
  useEffect(() => {
    const off = listenHost((message) => {
      if (message.type === MSG.INIT) {
        const data = message.payload || {};
        clearDirty();
        setPrintOpen(false);
        if (data.mode === "fill") {
          setLedgerData({
            snapshot: data.version?.snapshot || {},
            bindings: data.version?.bindings || [],
            paper: normalizePaper(data.version?.paper),
            values: { ...(data.values || {}) },
            meta: { ...(data.meta || {}), loadKey: `${Date.now()}` },
          });
          setPhase("fill");
        } else {
          const next = data.draft
            ? {
              snapshot: data.draft.snapshot,
              bindings: data.draft.bindings || [],
              paper: normalizePaper(data.draft.paper),
              loadKey: `${Date.now()}`,
            }
            : { ...buildNewDraft(), loadKey: `${Date.now()}` };
          setDraft(next);
          setPhase("template");
        }
      } else if (message.type === MSG.COLLECT) {
        const state = collectStateRef.current();
        postToHost(MSG.COLLECT_RESULT, state, message.requestId);
      } else if (message.type === MSG.SAVED) {
        clearDirty();
      }
    });
    if (!didPostReadyRef.current) {
      didPostReadyRef.current = true;
      postToHost(MSG.READY, {});
    }
    return off;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 草稿元信息变更推送（节流；不含快照本体）
  useEffect(() => {
    if (phase !== "template") return undefined;
    const timer = window.setTimeout(() => {
      postToHost(MSG.DRAFT_META, {
        title,
        bindingsCount: bindings.length,
        paper,
        dirty,
      });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [phase, title, bindings.length, paper, dirty]);

  // ==================== 模板编辑动作 ====================
  const captureSnapshot = useCallback(() => {
    const snapshot = workbookRef.current ? clone(workbookRef.current.save()) : null;
    if (!snapshot || !draftRef.current) return null;
    const next = { ...draftRef.current, snapshot };
    draftRef.current = next;
    setDraftState(next);
    return next;
  }, []);

  const applyTitle = useCallback(() => {
    const trimmed = title.trim();
    if (!worksheetRef.current || !trimmed) return;
    worksheetRef.current.getRange("A1").setValue(trimmed);
    const current = captureSnapshot();
    clearDirty();
    notifyLocal(`标题已写入模板 ${titleOf(current?.snapshot)}`);
  }, [captureSnapshot, title, clearDirty, notifyLocal]);

  const changeTitle = useCallback((value) => {
    setTitle(value);
    markDirty();
  }, [markDirty]);

  const updatePaper = useCallback((patch) => {
    const current = draftRef.current;
    if (!current) return;
    const next = {
      ...current,
      paper: {
        ...current.paper,
        ...patch,
        margins: patch.margins
          ? { ...current.paper.margins, ...patch.margins }
          : current.paper.margins,
      },
    };
    draftRef.current = next;
    setDraftState(next);
    markDirty();
  }, [markDirty]);

  const addBinding = useCallback(({ label, type, isRequired }) => {
    const range = selectedRange?.split(":")[0] || "A1";
    const current = draftRef.current;
    if (!current) return;
    if (current.bindings.some((item) => item.range === range)) {
      notifyLocal(`单元格 ${range} 已绑定其他字段`);
      return;
    }
    const nextBinding = {
      id: `bind-custom-${Date.now()}`,
      key: `custom_${Date.now()}`,
      label,
      section: "自定义字段",
      range,
      type,
      placeholder: "",
      is_required: Boolean(isRequired),
    };
    const next = { ...current, bindings: [...current.bindings, nextBinding] };
    draftRef.current = next;
    setDraftState(next);
    markDirty();
    notifyLocal(`已绑定 ${range}：${label}`);
  }, [markDirty, notifyLocal, selectedRange]);

  const batchBind = useCallback(({ labelPrefix, type }) => {
    const worksheet = worksheetRef.current;
    const current = draftRef.current;
    if (!worksheet || !current) return;
    const result = collectBatchBindings({
      worksheet,
      existingBindings: current.bindings,
      labelPrefix,
      type,
    });
    if (!result.additions.length) {
      notifyLocal(result.skipped
        ? `选区内 ${result.skipped} 个单元格均已绑定，无新增字段`
        : "请先选择要批量绑定的单元格区域");
      return;
    }
    const next = { ...current, bindings: [...current.bindings, ...result.additions] };
    draftRef.current = next;
    setDraftState(next);
    markDirty();
    notifyLocal(
      `已批量绑定 ${result.additions.length} 个字段`
      + `${result.skipped ? `，跳过 ${result.skipped} 个已绑定单元格` : ""}`
      + `${result.capped ? "；单次最多 200 个字段" : ""}`,
    );
  }, [markDirty, notifyLocal]);

  const removeBinding = useCallback((bindingId) => {
    const current = draftRef.current;
    if (!current) return;
    const next = { ...current, bindings: current.bindings.filter((item) => item.id !== bindingId) };
    draftRef.current = next;
    setDraftState(next);
    markDirty();
  }, [markDirty]);

  // ==================== 填写动作 ====================
  const updateFieldValue = useCallback((key, value) => {
    valuesRef.current = { ...valuesRef.current, [key]: value };
    markDirty();
  }, [markDirty]);

  // 填写值推送（节流；宿主用于脏值跟踪与保存。每次修改都会先 markDirty，
  // dirty 变化触发本 effect，valuesRef 在推送时读取最新值）
  useEffect(() => {
    if (phase !== "fill") return undefined;
    const timer = window.setTimeout(() => {
      postToHost(MSG.VALUES, { values: valuesRef.current, dirty: dirtyRef.current });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [phase, dirty, activeField]);

  const focusField = useCallback((key) => {
    setActiveField(key);
    window.setTimeout(() => {
      updateRects();
      document.querySelector(`[data-field-key="${key}"]`)?.focus();
    }, 80);
  }, [updateRects]);

  const requestExport = useCallback(() => {
    postToHost(MSG.EXPORT_PDF, {});
  }, []);

  // ==================== 打印预览文档 ====================
  const printDoc = useMemo(() => {
    if (!printOpen) return null;
    if (phase === "fill" && ledgerRef.current) {
      return renderPrintDocument({
        snapshot: clone(ledgerRef.current.snapshot),
        bindings: ledgerRef.current.bindings,
        values: valuesRef.current,
        paper: normalizePaper(ledgerRef.current.paper),
        meta: {
          templateName: ledgerRef.current.meta?.templateName || "维护台账",
          recordCode: ledgerRef.current.meta?.ledgerNo || "",
        },
        previewZoom,
      });
    }
    if (phase === "template" && draftRef.current) {
      const current = draftRef.current.snapshot && workbookRef.current
        ? clone(workbookRef.current.save())
        : clone(draftRef.current.snapshot);
      return renderPrintDocument({
        snapshot: current,
        bindings: draftRef.current.bindings,
        values: {},
        paper: draftRef.current.paper,
        meta: { templateName: title || "模板打印预览", recordCode: "模板草稿" },
        previewZoom,
      });
    }
    return null;
  }, [printOpen, phase, previewZoom, title]);

  const waiting = phase === "waiting";

  return (
    <div className="app">
      {waiting ? (
        <div className="editor-loading is-fullscreen">
          <span className="spinner" />
          正在等待宿主页面注入模板数据…
        </div>
      ) : (
        <React.Fragment>
          <div className={`app-body ${phase}`}>
            {phase === "template" ? (
              <TemplatePanel
                bindingCount={bindings.length}
                bindings={bindings}
                paper={paper}
                title={title}
                onTitleChange={changeTitle}
                onApplyTitle={applyTitle}
                selectedRange={selectedRange}
                onAddBinding={addBinding}
                onBatchBind={batchBind}
                onRemoveBinding={removeBinding}
                onChangePaper={updatePaper}
                dirty={dirty}
              />
            ) : (
              <FillPanel
                meta={ledger?.meta}
                bindings={bindings}
                values={valuesRef.current}
                activeField={activeField}
                onFocusField={focusField}
                onOpenPrint={() => setPrintOpen(true)}
              />
            )}

            <main className="sheet-column">
              <div className="sheet-strip">
                <div>
                  <strong>{phase === "template" ? "模板编辑视图" : "台账填写视图"}</strong>
                  <span>{phase === "template"
                    ? "Univer 原生网格 · 双击编辑、拖拽行列、合并与格式工具可用"
                    : "底表按创建时版本只读 · 输入控件按绑定单元格尺寸定位"}</span>
                </div>
                <div className="sheet-badges">
                  <span>{paper.size} {paper.orientation === "landscape" ? "横向" : "纵向"}</span>
                  <span>{dirty ? "有未保存修改" : "无未保存修改"}</span>
                </div>
              </div>
              <div className="sheet-stage" ref={stageRef}>
                <div id="univer-host" ref={hostRef} />
                {phase === "fill" && ledger && (
                  <FieldOverlay
                    bindings={bindings}
                    values={valuesRef.current}
                    rects={rects}
                    activeKey={activeField}
                    onChange={updateFieldValue}
                    onFocus={setActiveField}
                  />
                )}
                {editorLoading && (
                  <div className="editor-loading">
                    <span className="spinner" />
                    正在加载 Univer 表格引擎…
                  </div>
                )}
              </div>
              <div className="sheet-foot">
                <span>编辑器经消息桥与宿主页面通信；保存/发布/导出请在宿主页面操作。</span>
                <span>{phase === "fill" ? `台账编号：${ledger?.meta?.ledgerNo || "—"}` : "模板草稿由宿主保存到服务端"}</span>
              </div>
            </main>
          </div>

          {printOpen && (
            <PrintDialog
              doc={printDoc}
              paper={paper}
              locked={phase === "fill"}
              onChangePaper={updatePaper}
              onClose={() => setPrintOpen(false)}
              onExport={requestExport}
              exporting={exporting}
              iframeRef={iframeRef}
            />
          )}

          {toast && <div className={`toast ${toast.type}`} role="status">{toast.text}</div>}
        </React.Fragment>
      )}
    </div>
  );
}

/**
 * 脏值跟踪：订阅 Univer 命令流，选择/滚动/缩放/激活类命令不计，
 * 其余命令（输入、合并、行列操作、工具栏格式）一律视为修改。
 * 事件名在当前 preset 不可用时静默降级（仅面板动作与填写输入会标记脏值）。
 */
function attachDirtyTracker(univerAPI, onDirty) {
  try {
    const evt = univerAPI && univerAPI.Event;
    if (!evt || !evt.CommandExecuted || !univerAPI.addEvent) return;
    univerAPI.addEvent(evt.CommandExecuted, (params) => {
      const id = String(params?.command?.id || params?.id || '');
      if (!id || /selection|scroll|zoom|active|focus/i.test(id)) return;
      onDirty();
    });
  } catch {
    // 事件机制不可用时降级：脏值仅由面板动作标记
  }
}
