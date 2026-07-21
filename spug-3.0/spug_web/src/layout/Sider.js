import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Layout, Menu, Badge } from 'antd';
import { observer } from 'mobx-react';
import { hasPermission, history } from 'libs';
import styles from './layout.module.less';
import routes from '../routes';
import radioLicenseBadge from './RadioLicenseBadgeStore';
import approvalBadge from './ApprovalBadgeStore';
import contractAgreementBadge from './ContractAgreementBadgeStore';
import logo from './logo-spug-white.png';

let selectedKey = window.location.pathname;
const OpenKeysMap = {};

function buildOpenKeysMap(items, parents = []) {
  for (let item of items) {
    if (!item.title) continue;
    if (item.child) {
      buildOpenKeysMap(item.child, [...parents, item.title]);
    } else if (item.path) {
      OpenKeysMap[item.path] = parents.length ? parents : 1;
    }
  }
}

buildOpenKeysMap(routes);

// 子菜单 path -> 对应 badge store 的映射（仅当用户有对应权限时 store 才会拉取）
const CHILD_BADGE_STORES = {
  '/radio-license': () => radioLicenseBadge,
  '/station-frequency-approval': () => approvalBadge,
  '/contract-agreement': () => contractAgreementBadge,
};

// 父菜单 title -> 需要合计的子菜单 badge store 列表
const PARENT_BADGE_GROUPS = {
  '执照管理': [radioLicenseBadge, approvalBadge],
  '合同协议': [contractAgreementBadge],
};

/**
 * 独立的 badge 渲染子组件。
 *
 * 关键设计：用 observer 包裹，badge count 变化只触发本子组件重渲染，
 * 不触发父 Sider 重渲染，从而保持 Menu 的 items 引用稳定，
 * 避免 antd 4.x Menu 内部 Overflow 组件因 items 变化而触发
 * "Can't perform a React state update on anmounted component" 警告。
 */
const MenuBadge = observer(({stores}) => {
  const total = stores.reduce((sum, s) => sum + (s.loaded ? s.count : 0), 0);
  const allLoaded = stores.every(s => s.loaded);
  if (allLoaded && total > 0) {
    return <Badge count={total} offset={[6, -2]} size="small" style={{backgroundColor: '#ff4d4f'}}/>;
  }
  return null;
});

function handleRoute(item) {
  if (item.auth && !hasPermission(item.auth)) return
  if (!item.title) return;
  const menu = {label: item.title, key: item.path || item.title, icon: item.icon}
  if (item.child) {
    menu.children = []
    for (let sub of item.child) {
      const subMenu = handleRoute(sub)
      if (subMenu) menu.children.push(subMenu)
    }
  }
  return menu
}

const Sider = observer(function Sider(props) {
  const [openKeys, setOpenKeys] = useState([]);
  const [activeKey, setActiveKey] = useState(selectedKey);
  const collapsedRef = useRef(props.collapsed);
  const mountedRef = useRef(true);

  // 使用 ref 跟踪 collapsed 最新值，避免 useEffect 依赖变化导致监听器重建
  useEffect(() => {
    collapsedRef.current = props.collapsed;
  }, [props.collapsed]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Sync activeKey when route changes — 只注册一次，不依赖 collapsed
  useEffect(() => {
    const unlisten = history.listen(location => {
      if (!mountedRef.current) return;
      setActiveKey(location.pathname);
      const openKeysForPath = OpenKeysMap[location.pathname];
      if (openKeysForPath && openKeysForPath !== 1 && !collapsedRef.current) {
        setOpenKeys(prev => Array.from(new Set([...prev, ...openKeysForPath])))
      }
    });
    return unlisten;
  }, []);

  // Initial menu expansion — 只执行一次
  useEffect(() => {
    const tmp = window.location.pathname;
    const openKeysForPath = OpenKeysMap[tmp];
    if (openKeysForPath) {
      selectedKey = tmp;
      if (openKeysForPath !== 1) {
        setOpenKeys(prev => Array.from(new Set([...prev, ...openKeysForPath])))
      }
    }
  }, []);

  // 稳定化菜单项计算 — useMemo 代替 useState + useEffect
  const menus = useMemo(() => {
    const tmp = []
    for (let item of routes) {
      const menu = handleRoute(item)
      if (menu) tmp.push(menu)
    }
    return tmp;
  }, []);

  // 注入 badge：将 MenuBadge 子组件嵌入 label，不依赖 badge count 值
  // 这样 renderedMenus 引用稳定，badge count 变化由 MenuBadge 自身 observer 响应
  const injectBadge = useCallback((menu) => {
    if (!menu) return menu;
    // 子菜单：按 key 匹配 badge store
    if (menu.key && CHILD_BADGE_STORES[menu.key]) {
      const store = CHILD_BADGE_STORES[menu.key]();
      return {
        ...menu,
        label: (
          <span>
            {menu.label}
            <MenuBadge stores={[store]}/>
          </span>
        ),
      };
    }
    // 父菜单：合计所有子菜单 badge
    if (menu.children && menu.label) {
      const group = PARENT_BADGE_GROUPS[menu.label];
      const newChildren = menu.children.map(injectBadge);
      if (group) {
        return {
          ...menu,
          children: newChildren,
          label: (
            <span>
              {menu.label}
              <MenuBadge stores={group}/>
            </span>
          ),
        };
      }
      return { ...menu, children: newChildren };
    }
    return menu;
  }, []);

  // renderedMenus 不再依赖 badge count，引用稳定
  const renderedMenus = useMemo(() => {
    return menus.map(injectBadge);
  }, [menus, injectBadge]);

  const handleMenuSelect = useCallback(menu => {
    history.push(menu.key);
  }, []);

  return (
    <Layout.Sider width={208} collapsed={props.collapsed} className={styles.sider}>
      <div className={styles.logo}>
        <img src={logo} alt="Logo"/>
      </div>
      <div className={styles.menus} style={{height: `${document.body.clientHeight - 64}px`}}>
        <Menu
          theme="dark"
          mode="inline"
          items={renderedMenus}
          className={styles.menus}
          selectedKeys={[activeKey]}
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          onSelect={handleMenuSelect}/>
      </div>
    </Layout.Sider>
  )
})

export default Sider
