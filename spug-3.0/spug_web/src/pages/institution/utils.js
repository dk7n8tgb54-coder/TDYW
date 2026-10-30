/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import { http, hasPermission } from 'libs';

/**
 * 二进制下载：拦截器对 blob 已做 JSON 错误检查，失败时 reject（拦截器已提示）
 */
export function downloadFile(url, filename) {
  return http.get(url, {responseType: 'blob'}).then(response => {
    const blob = response.data;
    const link = document.createElement('a');
    link.href = window.URL.createObjectURL(blob);
    link.download = filename || 'download';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(link.href);
  });
}

export function formatSize(size) {
  if (size === undefined || size === null) return '-';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDateTime(value) {
  if (!value) return '-';
  return String(value).replace('T', ' ').slice(0, 19);
}

// ---------------------------------------------------------------------------
// 手册级入口可见性（与后端 services 的判定口径一致，后端仍独立校验）

/**
 * 可见已发布内容（can_view_published 前端口径）：
 * 查看角色；或编制角色且本手册允许编制者查看发布版；或模块管理权限。
 */
export function canViewPublished(manual) {
  if (!manual) return false;
  const roles = manual.my_roles || [];
  return roles.includes('view') ||
    (manual.editor_can_view_published && roles.includes('edit')) ||
    hasPermission('institution.manual.edit') ||
    hasPermission('institution.manual.config');
}

/**
 * 草稿工作区/待发布集合可见（_can_view_workspace 前端口径）：
 * 编制或发布角色，或模块管理权限。
 */
export function canViewWorkspace(manual) {
  if (!manual) return false;
  const roles = manual.my_roles || [];
  return roles.includes('edit') || roles.includes('publish') ||
    hasPermission('institution.manual.edit') ||
    hasPermission('institution.manual.config');
}
