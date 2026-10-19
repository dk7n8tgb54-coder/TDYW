import { createSeedWorkspace } from "./template";

const STORAGE_KEY = "native-ledger-poc.workspace.v1";
const MODE_KEY = "native-ledger-poc.ui.v1";
const CLEARED_KEY = "native-ledger-poc.cleared.v1";

export function loadWorkspace() {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return window.localStorage.getItem(CLEARED_KEY) === "1" ? null : createSeedWorkspace();
  try {
    const parsed = JSON.parse(raw);
    if (parsed?.schema !== 1 || !parsed.template?.versions?.length) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function saveWorkspace(workspace) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace));
  window.localStorage.removeItem(CLEARED_KEY);
}

export function resetWorkspace() {
  const workspace = createSeedWorkspace();
  saveWorkspace(workspace);
  return workspace;
}

export function clearWorkspace() {
  window.localStorage.removeItem(STORAGE_KEY);
  window.localStorage.removeItem(MODE_KEY);
  window.localStorage.setItem(CLEARED_KEY, "1");
}

export function loadUiState() {
  try {
    return JSON.parse(window.localStorage.getItem(MODE_KEY) || "{}");
  } catch {
    return {};
  }
}

export function saveUiState(state) {
  window.localStorage.setItem(MODE_KEY, JSON.stringify(state));
}

export function clone(value) {
  return JSON.parse(JSON.stringify(value));
}
