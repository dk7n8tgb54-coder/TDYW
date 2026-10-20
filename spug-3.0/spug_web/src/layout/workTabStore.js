/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 工作页签 Store（2026-10-19 导航改造；2026-10-20 数量上限与最近使用淘汰）。
 *
 * - 页签身份 = 路由 pathname：同一路由不重复开页签；带参数路由（如
 *   /upgrade/workbench/:id）按完整路径各占一个页签。
 * - 页签记住最后一次访问的完整 URL（含查询参数），切回时原样恢复，
 *   因此 ?detail=/?tab=/deep-link 类参数不丢失。
 * - 数量上限：除固定"工作台"外最多 MAX_WORK_TABS 个页签；打开第 7 个时
 *   自动淘汰"最近使用时间最早且无未保存内容"的可关闭页签（工作台不参与
 *   淘汰）；最近使用时间（ts）与显示顺序分开维护，切换页签只刷新 ts、
 *   不改变排列位置。若全部候选页签均有未保存内容，则不允许开新页签——
 *   由 WorkTabs 的 history.block 在导航发生前拦截并提示（checkNavigation）。
 * - 侧栏菜单/页内跳转 → history.push → WorkTabs 的 history.listen →
 *   syncLocation 统一开页签/激活页签，浏览器前进/后退与刷新后直接访问
 *   走同一条链路。
 * - 状态保留策略：切走页面即卸载（与既有菜单导航语义一致），筛选条件、
 *   分页与草稿由各页面既有 MobX 单例 store 天然保留；滚动位置按
 *   pathname 记录在 scrollMemory，由 WorkTabs 保存/恢复。
 * - 已开页签持久化到 sessionStorage（'spug.workTabs'，含最近使用 ts），
 *   刷新后恢复并按当前会话权限逐条复核；恢复数据超过上限时仅保留最近
 *   使用的页签。持久化数据附带会话身份标记（'spug.workTabs.session' =
 *   登录 token，每次登录重新生成）：重新登录或切换账号后丢弃上次页签与
 *   最近使用记录，从工作台/合法默认入口开始。
 * - "工作台"（/home）为固定页签：置顶、不可关闭，仅当账户有
 *   dashboard.dashboard.view 权限时存在（与路由注册口径一致）。
 * - 未保存内容登记（unsavedSources）：页面通过 useWorkTabUnsaved 声明
 *   "当前页签有未保存内容"（同一页面多处来源计数合并），有登记的页签
 *   不参与自动淘汰；页签手动关闭/淘汰/会话恢复时同步清理登记、滚动记忆
 *   与持久化记录。
 */
import {observable, action} from 'mobx';
import {history} from 'libs';
import {getFlatRoutes, resetRoutesCache, resolveRoute} from './routeMeta';

const STORAGE_KEY = 'spug.workTabs';
const SESSION_KEY = 'spug.workTabs.session';

/** 除固定"工作台"外允许同时打开的工作页签上限。 */
export const MAX_WORK_TABS = 6;

// 未保存内容登记自增序号（release 闭包凭它撤销自己的登记）
let unsavedSourceSeq = 0;

class WorkTabStore {
  @observable tabs = [];
  @observable activeKey = null;
  // pathname -> 最近一次滚动位置；非响应式数据，仅布局层读写
  scrollMemory = {};
  // pathname -> Set<来源id>；有任一来源即视为该页签有未保存内容
  unsavedSources = {};

  @action.bound syncLocation(location) {
    // 重定向、未知路径、隐藏无标题路由不建立页签
    const found = resolveRoute(location.pathname);
    if (!found) return;
    const key = location.pathname;
    const url = location.pathname + (location.search || '');
    const existing = this.tabs.find(tab => tab.key === key);
    if (existing) {
      existing.url = url;
      existing.ts = Date.now();
    } else {
      this._evictForNewTab();
      this.tabs.push({key, title: found.route.title, url, closable: key !== '/home', ts: Date.now()});
    }
    this.activeKey = key;
    this.persist();
  }

  @action.bound closeTab(key) {
    const index = this.tabs.findIndex(tab => tab.key === key);
    if (index < 0) return;
    if (this.tabs[index].closable === false) return;
    this.tabs.splice(index, 1);
    // 页签机制维护的伴随状态随关闭一并清理
    delete this.scrollMemory[key];
    delete this.unsavedSources[key];
    if (this.activeKey === key) {
      const next = this.tabs[index - 1] || this.tabs[0];
      if (next) {
        this.activeKey = next.key;
        history.push(next.url);
      } else {
        history.push(this.defaultPath());
      }
    }
    this.persist();
  }

  /**
   * 导航准入检查（WorkTabs 的 history.block 调用）：已开页签/不建页签路径
   * 直接放行；需要开新页签且未达上限放行；已达上限但存在可淘汰页签（非
   * 固定、无未保存内容）放行（淘汰由 syncLocation 执行）；全部候选均有
   * 未保存内容时阻止并给出提示文案。
   */
  checkNavigation(pathname) {
    if (!resolveRoute(pathname)) return {allowed: true};
    if (this.tabs.some(tab => tab.key === pathname)) return {allowed: true};
    if (this._closableTabs().length < MAX_WORK_TABS) return {allowed: true};
    if (this._findEvictable()) return {allowed: true};
    return {
      allowed: false,
      reason: `最多保留 ${MAX_WORK_TABS} 个工作页签，且已打开页签均有未保存内容：` +
        '请先保存或手动关闭部分页签后再打开新页面',
    };
  }

  /** 登记一条"该页签有未保存内容"来源，返回撤销登记的函数。 */
  addUnsavedSource(pathname) {
    if (!pathname) return () => {};
    const set = this.unsavedSources[pathname] || (this.unsavedSources[pathname] = new Set());
    const id = ++unsavedSourceSeq;
    set.add(id);
    return () => {
      const current = this.unsavedSources[pathname];
      if (!current) return;
      current.delete(id);
      if (!current.size) delete this.unsavedSources[pathname];
    };
  }

  hasUnsaved(pathname) {
    const set = this.unsavedSources[pathname];
    return !!set && set.size > 0;
  }

  /** Layout 挂载时调用：重置路由缓存（账户可能已切换）并恢复已开页签。 */
  @action.bound restore(location) {
    resetRoutesCache();
    const routeList = getFlatRoutes();
    const saved = this._loadSavedTabs();
    let tabs = [];
    const homeRoute = resolveRoute('/home', routeList);
    if (homeRoute) {
      tabs.push({key: '/home', title: homeRoute.route.title, url: '/home', closable: false, ts: Date.now()});
    }
    for (let item of saved) {
      if (!item || !item.key || tabs.some(tab => tab.key === item.key)) continue;
      const found = resolveRoute(item.key, routeList);
      if (!found) continue;
      tabs.push({
        key: item.key,
        title: found.route.title,
        url: item.url || item.key,
        closable: item.key !== '/home',
        ts: Number(item.ts) || Date.now(),
      });
    }
    // 历史持久化数据超过上限时仅保留最近使用的页签（显示顺序不变）
    const closable = tabs.filter(tab => tab.closable !== false);
    if (closable.length > MAX_WORK_TABS) {
      const keep = closable.slice()
        .sort((a, b) => (b.ts || 0) - (a.ts || 0))
        .slice(0, MAX_WORK_TABS)
        .map(tab => tab.key);
      tabs = tabs.filter(tab => tab.closable === false || keep.includes(tab.key));
    }
    this.tabs = tabs;
    this.scrollMemory = {};
    this.unsavedSources = {};
    this.syncLocation(location);
  }

  persist() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(this.tabs.map(({key, url, ts}) => ({key, url, ts}))));
    } catch (e) {
      // sessionStorage 不可用（隐私模式等）时页签仅在内存中生效
    }
  }

  /**
   * 读取持久化页签：会话身份标记与当前登录 token 不一致（重新登录、切换
   * 账号）时丢弃全部历史页签与最近使用记录；随后写入当前身份标记。
   */
  _loadSavedTabs() {
    let saved = [];
    try {
      saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]');
    } catch (e) {
      saved = [];
    }
    const token = sessionStorage.getItem('token') || '';
    const marker = sessionStorage.getItem(SESSION_KEY);
    if (!Array.isArray(saved) || marker !== token) saved = [];
    try {
      sessionStorage.setItem(SESSION_KEY, token);
    } catch (e) {
      // 同 persist：存储不可用时身份标记仅本次会话内有效
    }
    return saved;
  }

  _closableTabs() {
    return this.tabs.filter(tab => tab.closable !== false);
  }

  /** 可自动淘汰的页签：非固定（可关闭）且无未保存内容登记。 */
  _findEvictable() {
    let victim = null;
    for (let tab of this.tabs) {
      if (tab.closable === false || this.hasUnsaved(tab.key)) continue;
      if (!victim || tab.ts < victim.ts) victim = tab;
    }
    return victim;
  }

  /** 开新页签前腾位：已达上限时逐个淘汰最久未使用且可淘汰的页签。 */
  _evictForNewTab() {
    while (this._closableTabs().length >= MAX_WORK_TABS) {
      const victim = this._findEvictable();
      if (!victim) break;
      this.tabs.splice(this.tabs.indexOf(victim), 1);
      delete this.scrollMemory[victim.key];
      delete this.unsavedSources[victim.key];
    }
  }

  /** 无剩余页签时的兜底路由：第一个有权限的菜单页，否则个人中心。 */
  defaultPath() {
    const routes = getFlatRoutes();
    return routes.length ? routes[0].path : '/welcome/info';
  }
}

export default new WorkTabStore();
