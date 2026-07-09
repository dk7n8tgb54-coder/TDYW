/**
 * Lightweight context for document system folders.
 *
 * The active code is intentionally kept outside MobX to avoid coupling low-level
 * request helpers to page stores. System-folder parameters are only emitted on
 * their owning route, so stale page state cannot leak into the normal document
 * library.
 */

let _activeCode = null;

export const INDUSTRY_RULES_CODE = 'industry_rules';
export const INDUSTRY_RULES_PATH = '/document/industry-rules';

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

export function isIndustryRulesMode() {
  return _activeCode === INDUSTRY_RULES_CODE;
}

export function isIndustryRulesPath(pathname = getCurrentPathname()) {
  return pathname === INDUSTRY_RULES_PATH || pathname.startsWith(`${INDUSTRY_RULES_PATH}/`);
}

export function shouldUseSystemFolder(pathname = getCurrentPathname()) {
  return _activeCode === INDUSTRY_RULES_CODE && isIndustryRulesPath(pathname);
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
  INDUSTRY_RULES_CODE,
  INDUSTRY_RULES_PATH,
  setSystemFolder,
  getSystemFolder,
  isIndustryRulesMode,
  isIndustryRulesPath,
  shouldUseSystemFolder,
  appendSystemFolderParam,
  withSystemFolderParams,
};
