/**
 * Lightweight context for document system folders.
 *
 * The active code is intentionally kept outside MobX to avoid coupling low-level
 * request helpers to page stores. System-folder parameters are only emitted on
 * their owning route, so stale page state cannot leak into the normal document
 * library.
 */

let _activeCode = null;

export const PARTY_BUILDING_DOCUMENTS_CODE = 'party_building_documents';
export const PARTY_BUILDING_DOCUMENTS_PATH = '/document/party-building-documents';

function getCurrentPathname() {
  if (typeof window === 'undefined') return '';
  return window.location?.pathname || '';
}

export function setSystemFolder(code) {
  _activeCode = code || null;
}

export function getSystemFolder() {
  return _activeCode;
}

export function isPartyBuildingDocumentsMode() {
  return _activeCode === PARTY_BUILDING_DOCUMENTS_CODE;
}

export function isPartyBuildingDocumentsPath(pathname = getCurrentPathname()) {
  return pathname === PARTY_BUILDING_DOCUMENTS_PATH || pathname.startsWith(`${PARTY_BUILDING_DOCUMENTS_PATH}/`);
}

export function shouldUseSystemFolder(pathname = getCurrentPathname()) {
  return _activeCode === PARTY_BUILDING_DOCUMENTS_CODE && isPartyBuildingDocumentsPath(pathname);
}

/**
 * Append system_folder to direct URLs used by window.open, media tags and links.
 */
export function appendSystemFolderParam(url, pathname = getCurrentPathname()) {
  if (!shouldUseSystemFolder(pathname)) return url;
  const sep = url.indexOf('?') >= 0 ? '&' : '?';
  return `${url}${sep}system_folder=${encodeURIComponent(_activeCode)}`;
}

/**
 * Inject system_folder into an axios params object without mutating the input.
 */
export function withSystemFolderParams(params = {}, pathname = getCurrentPathname()) {
  if (!shouldUseSystemFolder(pathname)) return params;
  return { ...params, system_folder: _activeCode };
}

export default {
  PARTY_BUILDING_DOCUMENTS_CODE,
  PARTY_BUILDING_DOCUMENTS_PATH,
  setSystemFolder,
  getSystemFolder,
  isPartyBuildingDocumentsMode,
  isPartyBuildingDocumentsPath,
  shouldUseSystemFolder,
  appendSystemFolderParam,
  withSystemFolderParams,
};
