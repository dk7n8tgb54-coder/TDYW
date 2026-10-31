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
// 独立校验）。2026-10-31 二轮权限模型改造：可见性由 逐本账号授权行
// （my_roles）与 手册所有者/平台超级管理员标志（is_owner/is_admin，后端
// 下发）决定，不以模块权限码（edit/config）直通——模块权限码只授予功能
// 入口资格；所有者自动拥有该手册全部权限（含发布版/工作区可见），
// 「编制授权者可查看发布版」开关已废除。

/**
 * 可见已发布内容（can_view_published 前端口径）：
 * 查看授权；或手册所有者；或平台超级管理员（后端下发 is_admin）。
 */
export function canViewPublished(manual) {
  if (!manual) return false;
  const roles = manual.my_roles || [];
  return roles.includes('view') ||
    !!manual.is_owner || !!manual.is_admin;
}

/**
 * 草稿工作区/待发布集合可见（_can_view_workspace 前端口径）：
 * 编制或发布授权，或手册所有者，或平台超级管理员。
 */
export function canViewWorkspace(manual) {
  if (!manual) return false;
  const roles = manual.my_roles || [];
  return roles.includes('edit') || roles.includes('publish') ||
    !!manual.is_owner || !!manual.is_admin;
}
