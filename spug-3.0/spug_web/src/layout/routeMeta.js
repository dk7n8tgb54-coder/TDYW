/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 路由元信息帮助模块（2026-10-19 导航改造）。
 *
 * 工作页签与 Header 面包屑共用一份基于 routes.js 的路径 → 标题/层级映射：
 * - 有 title 的菜单路由：页签标题与面包屑层级直接取自路由配置；
 * - 隐藏路由（无 title）：通过 tabTitle / tabCrumbs 显式声明归属与标题，
 *   声明不完整的不进入页签；
 * - hideInTab：兼容重定向、休眠路由等不建立页签的路径；
 * - 权限过滤与 initRoutes 注册路由使用同一 hasPermission 口径，
 *   无权限路由既不会被注册也不会出现在页签或面包屑中。
 */
import {matchPath} from 'react-router-dom';
import {hasPermission} from 'libs';
import routes from '../routes';

let cachedRoutes = null;

/**
 * 拍平路由树为页签/面包屑可用的条目列表。
 * out 每项：{path, title, crumbs}，crumbs 为"首页"之后的层级标题数组。
 */
export function flattenRoutes(items, parents = [], out = []) {
  for (let item of items) {
    if (item.hideInTab) continue;
    const nextParents = item.title ? [...parents, item.title] : parents;
    if (item.child) {
      flattenRoutes(item.child, nextParents, out);
      continue;
    }
    if (!item.path || !item.component) continue;
    const title = item.title || item.tabTitle;
    if (!title) continue;
    if (item.auth && !hasPermission(item.auth)) continue;
    out.push({path: item.path, title, crumbs: item.tabCrumbs || parents});
  }
  return out;
}

/** 获取当前会话的路由条目（按权限过滤）。登录/切换账户后由 resetRoutesCache 失效。 */
export function getFlatRoutes() {
  if (!cachedRoutes) cachedRoutes = flattenRoutes(routes);
  return cachedRoutes;
}

export function resetRoutesCache() {
  cachedRoutes = null;
}

/** 按路径匹配路由条目，返回 {route, match} 或 null（重定向/未知/无权限路径）。 */
export function resolveRoute(pathname, routeList) {
  const list = routeList || getFlatRoutes();
  for (let route of list) {
    const match = matchPath(pathname, {path: route.path, exact: true});
    if (match) return {route, match};
  }
  return null;
}

/** 路径对应的面包屑标题数组（含"首页"）；未知路径只显示"首页"。 */
export function crumbsFor(pathname) {
  const found = resolveRoute(pathname);
  if (!found) return ['首页'];
  return ['首页', ...found.route.crumbs, found.route.title];
}
