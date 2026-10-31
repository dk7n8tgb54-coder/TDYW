/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import { http } from 'libs';

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
// 手册级入口可见性（与后端 authorization_services 的判定口径一致，后端仍
// 独立校验）。2026-10-31 授权模型改造：可见性只由 逐本账号授权行（my_roles）
// 与 手册所有者/制度管理员标志（is_owner/is_admin）决定，不再以模块权限码
// （edit/config）直通——模块权限码只授予功能入口资格；所有者身份同样不
// 自动获得发布版可见或工作区可见。

/**
 * 可见已发布内容（can_view_published 前端口径）：
 * 查看授权；或编制授权且本手册允许编制授权者查看发布版；或制度管理员。
 * 注意：手册所有者身份不自动可见发布版（后端同口径）。
 */
export function canViewPublished(manual) {
  if (!manual) return false;
  const roles = manual.my_roles || [];
  return roles.includes('view') ||
    (manual.editor_can_view_published && roles.includes('edit')) ||
    !!manual.is_admin;
}

/**
 * 草稿工作区/待发布集合可见（_can_view_workspace 前端口径）：
 * 编制或发布授权，或手册所有者，或制度管理员。
 */
export function canViewWorkspace(manual) {
  if (!manual) return false;
  const roles = manual.my_roles || [];
  return roles.includes('edit') || roles.includes('publish') ||
    !!manual.is_owner || !!manual.is_admin;
}
