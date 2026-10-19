import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createLedgerUniver, loadSnapshot } from "./univer";
import {
  DEFAULT_PAPER,
  PAPER_PRESETS,
  getLatestVersion,
} from "./template";
import {
  clearWorkspace,
  clone,
  loadWorkspace,
  resetWorkspace,
  saveWorkspace,
} from "./storage";
import { renderPrintDocument } from "./print";
import { collectBatchBindings } from "./bindings";
import { readViewportScroll } from "./scroll";
import TemplatePanel from "./components/TemplatePanel";
import FillPanel from "./components/FillPanel";
import PrintDialog from "./components/PrintDialog";
import FieldOverlay from "./components/FieldOverlay";

const SHEET_ID = "ledger";

function titleOf(snapshot) {
  return snapshot?.sheets?.[SHEET_ID]?.cellData?.[0]?.[0]?.v || "";
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function recordCode(records) {
  return `TX-2026-Q3-${String(records.length + 1).padStart(3, "0")}`;
}

function buildEmptyValues(bindings) {
  return Object.fromEntries(bindings.map((binding) => [binding.key, binding.key === "inspect_date" ? today() : ""]));
}

function buildSession(record, version) {
  return {
    recordId: record?.id || null,
    code: record?.code || "",
    title: record?.title || "新建维护台账",
    versionId: record?.versionId || version.id,
    status: record?.status || "草稿",
    values: { ...buildEmptyValues(version.bindings), ...(record?.values || {}) },
    saved: Boolean(record),
    loadKey: `${record?.id || "new"}-${Date.now()}`,
  };
}

function previewZoomFor(paper) {
  const dims = PAPER_PRESETS[paper.size] || PAPER_PRESETS.A4;
  const widthMm = paper.orientation === "landscape" ? dims.height : dims.width;
  const widthPx = widthMm * (96 / 25.4);
  const available = Math.max(420, window.innerWidth - (window.innerWidth > 900 ? 120 : 48));
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

export default function App() {
  const [workspace, setWorkspaceState] = useState(() => loadWorkspace());
  const workspaceRef = useRef(workspace);
  const [mode, setMode] = useState("template");
  const [session, setSession] = useState(null);
  const [draftTitle, setDraftTitle] = useState(() => titleOf(workspace?.template?.draft?.snapshot));
  const [selectedRange, setSelectedRange] = useState("");
  const [activeField, setActiveField] = useState(null);
  const [rects, setRects] = useState({});
  const [engineReady, setEngineReady] = useState(0);
  const [editorLoading, setEditorLoading] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
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

  const hasWorkspace = Boolean(workspace);
  const versions = workspace?.template?.versions || [];
  const currentVersionId = workspace?.template?.currentVersionId;
  const activeVersion = workspace ? getLatestVersion(workspace) : null;
  const sessionVersion = session ? versions.find((item) => item.id === session.versionId) : null;
  const bindings = mode === "fill" && sessionVersion
    ? sessionVersion.bindings
    : workspace?.template?.draft?.bindings || [];
  const paper = workspace?.template?.draft?.paper || DEFAULT_PAPER;

  const commitWorkspace = useCallback((updater) => {
    const previous = workspaceRef.current;
    const next = typeof updater === "function" ? updater(previous) : updater;
    if (!next) return;
    workspaceRef.current = next;
    setWorkspaceState(next);
    try {
      saveWorkspace(next);
    } catch {
      setToast({ type: "error", text: "浏览器本地存储写入失败，请检查存储空间。" });
    }
  }, []);

  const notify = useCallback((text, type = "ok") => {
    setToast({ text, type });
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!hasWorkspace || !hostRef.current) return undefined;
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
  }, [hasWorkspace]);

  useEffect(() => {
    if (!engineReady || !apiRef.current || !workspaceRef.current) return;
    const current = workspaceRef.current;
    let snapshot;
    let effectiveBindings;
    if (mode === "fill" && session) {
      const version = current.template.versions.find((item) => item.id === session.versionId) || getLatestVersion(current);
      snapshot = clone(version.snapshot);
      effectiveBindings = version.bindings;
    } else {
      snapshot = clone(current.template.draft.snapshot);
      effectiveBindings = current.template.draft.bindings;
    }
    snapshot.id = `native-ledger-${Date.now()}`;
    const hostWidth = hostRef.current?.clientWidth || 900;
    const hostHeight = hostRef.current?.clientHeight || 800;
    const zoom = mode === "fill"
      ? Math.max(0.36, Math.min(0.8, hostWidth / 1408, (hostHeight - 12) / 1132))
      : Math.max(0.45, Math.min(0.8, hostWidth / 1320));
    setEditorLoading(true);
    const loaded = loadSnapshot(apiRef.current, currentIdRef.current, snapshot, zoom);
    currentIdRef.current = loaded.id;
    workbookRef.current = loaded.fWorkbook;
    worksheetRef.current = loaded.fWorksheet;
    window.__nativeLedgerDebug = {
      api: apiRef.current,
      worksheet: loaded.fWorksheet,
      rect: (a1) => {
        const r = loaded.fWorksheet.getRange(a1).getCellRect();
        return { left: r.left, top: r.top, width: r.width, height: r.height, zoom: loaded.fWorksheet.getZoom?.() };
      },
      scroll: () => readViewportScroll(loaded.fWorksheet),
      selection: () => loaded.fWorksheet.getSelection().getActiveRangeList().map((range) => range.getA1Notation()),
    };
    setActiveField(null);
    setRects({});

    if (mode === "fill" && session) {
      window.setTimeout(() => {
        for (const binding of effectiveBindings) {
          try {
            loaded.fWorksheet.getRange(binding.range).setValue(session.values[binding.key] ?? "");
          } catch {
            // A stale binding is reported in the binding panel, not here.
          }
        }
        const version = current.template.versions.find((item) => item.id === session.versionId) || getLatestVersion(current);
        try {
          loaded.fWorksheet.getRange("D2").setValue(`台账编号：${session.code || "未编号"}`);
          loaded.fWorksheet.getRange("G2").setValue(`维护日期：${session.values.inspect_date || today()}`);
          loaded.fWorksheet.getRange("M2").setValue(`模板版本：${version.label}`);
        } catch {
          // Header metadata is supplemental to the bound record fields.
        }
        loaded.fWorksheet.getWorksheetPermission().setReadOnly().catch(() => {});
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
  }, [engineReady, mode, session?.loadKey, reloadToken]);

  useEffect(() => {
    if (mode !== "template" || !engineReady) return undefined;
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
  }, [mode, engineReady]);

  const updateRects = useCallback(() => {
    if (mode !== "fill" || !worksheetRef.current || !stageRef.current) return;
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
    const frozenHeight = (skeleton?.rowHeightAccumulation?.[3] || 0)
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
          width > 4 &&
          height > 4 &&
          left + width > 0 &&
          top + height > mainTop &&
          left < stage.width &&
          top < stage.height
        ) {
          next[binding.key] = { left, top, width, height };
        }
      } catch {
        // Ignore cells that cannot be measured yet.
      }
    }
    setRects((previous) => (sameRects(previous, next) ? previous : next));
  }, [mode, bindings]);

  useEffect(() => {
    if (mode !== "fill" || !engineReady) return undefined;
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
  }, [mode, engineReady, updateRects, session?.loadKey]);

  useEffect(() => {
    if (!printOpen) return undefined;
    const update = () => setPreviewZoom(previewZoomFor(paper));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [printOpen, paper.size, paper.orientation]);

  const openRecord = useCallback((recordId) => {
    const current = workspaceRef.current;
    const record = current?.records.find((item) => item.id === recordId);
    if (!current || !record) return;
    const version = current.template.versions.find((item) => item.id === record.versionId) || getLatestVersion(current);
    setSession(buildSession(record, version));
    setMode("fill");
  }, []);

  const newRecord = useCallback(() => {
    const current = workspaceRef.current;
    if (!current) return;
    const version = getLatestVersion(current);
    const session = buildSession({
      id: null,
      code: recordCode(current.records),
      title: "新建维护台账",
      versionId: version.id,
      status: "草稿",
      values: {},
    }, version);
    setSession(session);
    setMode("fill");
  }, []);

  const switchMode = useCallback((next) => {
    if (next === "fill" && !session) {
      const current = workspaceRef.current;
      if (current?.records.length) {
        openRecord(current.records[0].id);
      } else {
        newRecord();
      }
      return;
    }
    setMode(next);
  }, [session, openRecord, newRecord]);

  const captureDraft = useCallback(() => {
    const current = workspaceRef.current;
    const snapshot = workbookRef.current?.save();
    if (!current || !snapshot) return current;
    const next = {
      ...current,
      template: {
        ...current.template,
        draft: {
          ...current.template.draft,
          snapshot,
          updatedAt: new Date().toISOString(),
        },
      },
    };
    commitWorkspace(next);
    return next;
  }, [commitWorkspace]);

  const applyTitle = useCallback(() => {
    if (!worksheetRef.current || !draftTitle.trim()) return;
    worksheetRef.current.getRange("A1").setValue(draftTitle.trim());
    const current = captureDraft();
    setDirty(false);
    notify(`标题已写入模板 ${titleOf(current?.template?.draft?.snapshot)}`);
  }, [captureDraft, draftTitle, notify]);

  const saveDraft = useCallback(() => {
    captureDraft();
    setDirty(false);
    notify("模板草稿已保存到浏览器本地存储");
  }, [captureDraft, notify]);

  const publishVersion = useCallback(() => {
    const current = captureDraft();
    if (!current) return;
    const number = current.template.versions.length + 1;
    const snapshot = clone(current.template.draft.snapshot);
    if (snapshot.sheets?.[SHEET_ID]?.cellData?.[1]?.[12]) {
      snapshot.sheets[SHEET_ID].cellData[1][12].v = `模板版本：v${number}`;
    }
    const version = {
      id: `ver-v${number}-${Date.now()}`,
      label: `v${number}`,
      note: "用户发布的模板版本",
      createdAt: new Date().toISOString(),
      snapshot,
      bindings: clone(current.template.draft.bindings),
      paper: clone(current.template.draft.paper),
    };
    commitWorkspace({
      ...current,
      template: {
        ...current.template,
        currentVersionId: version.id,
        draft: { ...current.template.draft, snapshot: clone(snapshot) },
        versions: [...current.template.versions, version],
      },
    });
    setDirty(false);
    notify(`模板已发布为 ${version.label}，新台账将使用该版本`);
  }, [captureDraft, commitWorkspace, notify]);

  const updatePaper = useCallback((patch) => {
    commitWorkspace((current) => ({
      ...current,
      template: {
        ...current.template,
        draft: {
          ...current.template.draft,
          paper: {
            ...current.template.draft.paper,
            ...patch,
            margins: patch.margins
              ? { ...current.template.draft.paper.margins, ...patch.margins }
              : current.template.draft.paper.margins,
          },
        },
        updatedAt: new Date().toISOString(),
      },
    }));
    setDirty(true);
  }, [commitWorkspace]);

  const addBinding = useCallback(({ label, type }) => {
    const range = selectedRange?.split(":")[0] || "A1";
    commitWorkspace((current) => {
      const nextBinding = {
        id: `bind-custom-${Date.now()}`,
        key: `custom_${Date.now()}`,
        label,
        section: "自定义字段",
        range,
        type,
        placeholder: "",
      };
      return {
        ...current,
        template: {
          ...current.template,
          draft: {
            ...current.template.draft,
            bindings: [...current.template.draft.bindings, nextBinding],
          },
        },
      };
    });
    setDirty(true);
    notify(`已绑定 ${range}：${label}`);
  }, [commitWorkspace, notify, selectedRange]);

  const batchBind = useCallback(({ labelPrefix, type }) => {
    const worksheet = worksheetRef.current;
    const current = workspaceRef.current;
    if (!worksheet || !current) return;
    const result = collectBatchBindings({
      worksheet,
      existingBindings: current.template.draft.bindings,
      labelPrefix,
      type,
    });
    if (!result.additions.length) {
      notify(
        result.skipped
          ? `选区内 ${result.skipped} 个单元格均已绑定，无新增字段`
          : "请先选择要批量绑定的单元格区域",
        "error",
      );
      return;
    }
    commitWorkspace((workspace) => ({
      ...workspace,
      template: {
        ...workspace.template,
        draft: {
          ...workspace.template.draft,
          bindings: [...workspace.template.draft.bindings, ...result.additions],
        },
      },
    }));
    setDirty(true);
    notify(
      `已批量绑定 ${result.additions.length} 个字段`
      + `${result.skipped ? `，跳过 ${result.skipped} 个已绑定单元格` : ""}`
      + `${result.capped ? "；单次最多 200 个字段" : ""}`,
    );
  }, [commitWorkspace, notify]);

  const removeBinding = useCallback((bindingId) => {
    commitWorkspace((current) => ({
      ...current,
      template: {
        ...current.template,
        draft: {
          ...current.template.draft,
          bindings: current.template.draft.bindings.filter((item) => item.id !== bindingId),
        },
      },
    }));
    setDirty(true);
  }, [commitWorkspace]);

  const updateField = useCallback((key, value) => {
    setSession((current) => current && ({
      ...current,
      saved: false,
      values: { ...current.values, [key]: value },
    }));
    if (key === "inspect_date" && worksheetRef.current) {
      try {
        worksheetRef.current.getRange("G2").setValue(`维护日期：${value || today()}`);
      } catch {
        // The meta row is display-only on the read-only fill sheet.
      }
    }
  }, []);

  const updateRecordCode = useCallback((value) => {
    setSession((current) => current && ({ ...current, code: value, saved: false }));
    if (worksheetRef.current) {
      try {
        worksheetRef.current.getRange("D2").setValue(`台账编号：${value || "未编号"}`);
      } catch {
        // The meta row is display-only on the read-only fill sheet.
      }
    }
  }, []);

  const focusField = useCallback((key) => {
    setActiveField(key);
    window.setTimeout(() => {
      updateRects();
      document.querySelector(`[data-field-key="${key}"]`)?.focus();
    }, 80);
  }, [updateRects]);

  const saveRecord = useCallback(() => {
    if (!session || !workspaceRef.current) return;
    setSaving(true);
    window.setTimeout(() => {
      const current = workspaceRef.current;
      const recordId = session.recordId || `rec-${Date.now()}`;
      const record = {
        id: recordId,
        code: session.code.trim() || recordCode(current.records),
        title: session.title.trim() || "维护台账",
        versionId: session.versionId,
        values: clone(session.values),
        status: "已填写",
        updatedAt: new Date().toISOString(),
      };
      const records = session.recordId
        ? current.records.map((item) => (item.id === recordId ? record : item))
        : [record, ...current.records];
      commitWorkspace({ ...current, records });
      setSession((value) => value && ({ ...value, recordId, code: record.code, title: record.title, saved: true, status: "已填写" }));
      setSaving(false);
      notify("台账已保存，可直接关闭页面后重新打开");
    }, 160);
  }, [commitWorkspace, notify, session]);

  const printDoc = useMemo(() => {
    if (!printOpen || !workspace || !session) return null;
    const version = versions.find((item) => item.id === session.versionId) || activeVersion;
    const snapshot = clone(version.snapshot);
    const sheet = snapshot.sheets?.[SHEET_ID];
    if (sheet?.cellData?.[1]) {
      sheet.cellData[1][3] = { ...(sheet.cellData[1][3] || {}), v: `台账编号：${session.code}` };
      sheet.cellData[1][6] = { ...(sheet.cellData[1][6] || {}), v: `维护日期：${session.values.inspect_date || today()}` };
      sheet.cellData[1][12] = { ...(sheet.cellData[1][12] || {}), v: `模板版本：${version.label}` };
    }
    return renderPrintDocument({
      snapshot,
      bindings: version.bindings,
      values: session.values,
      paper,
      record: { code: session.code },
      templateName: workspace.template.name,
      previewZoom,
    });
  }, [printOpen, workspace, session, versions, activeVersion, paper, previewZoom]);

  const exportPdf = useCallback(async () => {
    if (!printDoc || !session) return;
    setExporting(true);
    try {
      const response = await fetch("/api/export-pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          html: printDoc.html,
          filename: `native-ledger-${paper.size}-${paper.orientation}.pdf`,
        }),
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "PDF 生成失败");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `native-ledger-${session.code}-${paper.size}-${paper.orientation}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      notify("PDF 已生成并开始下载");
    } catch (error) {
      notify(`PDF 生成失败：${error.message}`, "error");
    } finally {
      setExporting(false);
    }
  }, [printDoc, session, paper.size, paper.orientation, notify]);

  const resetSample = useCallback(() => {
    const next = resetWorkspace();
    workspaceRef.current = next;
    setWorkspaceState(next);
    setSession(null);
    setMode("template");
    setDraftTitle(titleOf(next.template.draft.snapshot));
    setDirty(false);
    setPrintOpen(false);
    setReloadToken((value) => value + 1);
    notify("已恢复示例模板和示例台账");
  }, [notify]);

  const clearAll = useCallback(() => {
    if (!window.confirm("确认清空模板、字段绑定和全部台账记录？该操作只影响浏览器本地样板数据。")) return;
    clearWorkspace();
    workspaceRef.current = null;
    setWorkspaceState(null);
    setSession(null);
    setMode("template");
    setPrintOpen(false);
    setDirty(false);
    notify("样板数据已清空；可随时恢复示例");
  }, [notify]);

  useEffect(() => {
    if (workspace?.template?.draft?.snapshot && !draftTitle) {
      setDraftTitle(titleOf(workspace.template.draft.snapshot));
    }
  }, [workspace, draftTitle]);

  if (!workspace) {
    return (
      <div className="empty-page">
        <div className="empty-card">
          <span className="eyebrow">原生维护台账 · Univer POC</span>
          <h1>样板数据已清空</h1>
          <p>模板、字段绑定与台账记录均保存在本浏览器本地存储。恢复示例后可重新走完制作、填写和打印流程。</p>
          <button className="button primary" onClick={resetSample}>恢复示例数据</button>
        </div>
      </div>
    );
  }

  return (
    <div className="platform">
      <aside className="platform-sider">
        <div className="platform-logo">
          <span className="platform-logo-mark">✈</span>
          <div>
            <strong>空管综合运维</strong>
            <small>MANAGEMENT PLATFORM</small>
          </div>
        </div>
        <div className="sider-menu">
          <div className="sider-group">设备管理</div>
          <div className="sider-item is-active">
            <span className="sider-icon">▤</span>
            维护台账
            <em>样板</em>
          </div>
          <div className="sider-item"><span className="sider-icon">◈</span>设备生命周期</div>
          <div className="sider-item"><span className="sider-icon">☷</span>巡检记录</div>
          <div className="sider-group">系统</div>
          <div className="sider-item"><span className="sider-icon">⚙</span>系统设置</div>
        </div>
        <div className="sider-foot">
          原生台账样板
          <span>本地数据 · 不接生产</span>
        </div>
      </aside>

      <div className="platform-shell">
        <header className="platform-header">
          <div className="header-left">
            <span className="header-trigger">☰</span>
            <span className="header-title">维护台账</span>
            <span className="header-divider" />
            <span className="header-sub">原生样板</span>
          </div>
          <div className="header-right">
            <span className="header-env">开发环境</span>
            <span className="header-user">管理员</span>
            <span className="header-avatar">管</span>
          </div>
        </header>

        <main className="platform-content">
          <div className="platform-breadcrumb">
            首页 <span>/</span> 设备管理 <span>/</span> 维护台账 <span>/</span> <b>原生样板</b>
          </div>

          <div className="page-head">
            <div>
              <h1>维护台账原生样板</h1>
              <p>Univer 1.1.0 表格引擎 · 模板制作、台账填写与真实分页打印验证</p>
            </div>
            <div className="page-head-actions">
              <div className="page-meta">
                <span className="status-dot" />
                <span>{activeVersion?.label} · {bindings.length} 字段</span>
                <span className="page-meta-divider">|</span>
                <span>{dirty ? "模板有未保存修改" : "本地草稿已保存"}</span>
              </div>
              {mode === "fill" && (
                <button className="button" onClick={() => setPrintOpen(true)} disabled={!session}>
                  打印预览
                </button>
              )}
            </div>
          </div>

          <div className="page-tabs" role="tablist" aria-label="工作模式">
            <button id="tab-template" role="tab" aria-selected={mode === "template"} className={mode === "template" ? "is-active" : ""} onClick={() => switchMode("template")}>模板制作</button>
            <button id="tab-fill" role="tab" aria-selected={mode === "fill"} className={mode === "fill" ? "is-active" : ""} onClick={() => switchMode("fill")}>填写台账</button>
          </div>

          <section className="workspace-card">
            <div className={`app-body ${mode}`}>
              {mode === "template" ? (
                <TemplatePanel
                  bindingCount={bindings.length}
                  bindings={bindings}
                  paper={paper}
                  title={draftTitle}
                  onTitleChange={(value) => { setDraftTitle(value); setDirty(true); }}
                  onApplyTitle={applyTitle}
                  selectedRange={selectedRange}
                  onAddBinding={addBinding}
                  onBatchBind={batchBind}
                  onRemoveBinding={removeBinding}
                  versions={versions}
                  currentVersionId={currentVersionId}
                  onChangePaper={updatePaper}
                  onSaveDraft={saveDraft}
                  onPublish={publishVersion}
                  onReset={resetSample}
                  onClear={clearAll}
                  dirty={dirty}
                />
              ) : (
                <FillPanel
                  session={session}
                  records={workspace.records}
                  versions={versions}
                  bindings={bindings}
                  activeField={activeField}
                  onOpenRecord={openRecord}
                  onNewRecord={newRecord}
                  onSaveRecord={saveRecord}
                  onCodeChange={updateRecordCode}
                  onTitleChange={(value) => setSession((current) => current && ({ ...current, title: value, saved: false }))}
                  onFocusField={focusField}
                  onOpenPrint={() => setPrintOpen(true)}
                  saving={saving}
                  onReset={resetSample}
                  onClear={clearAll}
                />
              )}

              <main className="sheet-column">
                <div className="sheet-strip">
                  <div>
                    <strong>{mode === "template" ? "模板编辑视图" : "台账填写视图"}</strong>
                    <span>{mode === "template" ? "Univer 原生网格 · 双击编辑、拖拽行列、合并与格式工具可用" : "底表只读 · 输入控件按绑定单元格尺寸定位"}</span>
                  </div>
                  <div className="sheet-badges">
                    <span>{paper.size} {paper.orientation === "landscape" ? "横向" : "纵向"}</span>
                    <span>{mode === "template" ? `${versions.length} 个发布版本` : `模板 ${versions.find((v) => v.id === session?.versionId)?.label || "—"}`}</span>
                  </div>
                </div>
                <div className="sheet-stage" ref={stageRef}>
                  <div id="univer-host" ref={hostRef} />
                  {mode === "fill" && session && (
                    <FieldOverlay
                      bindings={bindings}
                      values={session.values}
                      rects={rects}
                      activeKey={activeField}
                      onChange={updateField}
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
                  <span>数据仅保存在浏览器 localStorage；不调用生产接口、不写入正式台账库。</span>
                  <span>{mode === "fill" && session ? `当前记录：${session.code}` : "模板草稿自动保存在本机"}</span>
                </div>
              </main>
            </div>
          </section>
        </main>
      </div>

      {printOpen && (
        <PrintDialog
          doc={printDoc}
          paper={paper}
          onChangePaper={updatePaper}
          onClose={() => setPrintOpen(false)}
          onExport={exportPdf}
          exporting={exporting}
          iframeRef={iframeRef}
        />
      )}

      {toast && <div className={`toast ${toast.type}`} role="status">{toast.text}</div>}
    </div>
  );
}
