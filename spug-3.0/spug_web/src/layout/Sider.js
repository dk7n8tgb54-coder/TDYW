import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Layout, Menu } from 'antd';
import { hasPermission, history } from 'libs';
import styles from './layout.module.less';
import routes from '../routes';
import logo from './logo-spug-white.png';

let selectedKey = window.location.pathname;
const OpenKeysMap = {};
for (let item of routes) {
  if (item.child) {
    for (let sub of item.child) {
      if (sub.title) OpenKeysMap[sub.path] = item.title
    }
  } else if (item.title) {
    OpenKeysMap[item.path] = 1
  }
}

function handleRoute(item) {
  if (item.auth && !hasPermission(item.auth)) return
  if (!item.title) return;
  const menu = {label: item.title, key: item.path, icon: item.icon}
  if (item.child) {
    menu.children = []
    for (let sub of item.child) {
      const subMenu = handleRoute(sub)
      if (subMenu) menu.children.push(subMenu)
    }
  }
  return menu
}

export default function Sider(props) {
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
      const openKey = OpenKeysMap[location.pathname];
      if (openKey && openKey !== 1 && !collapsedRef.current) {
        setOpenKeys(prev => prev.includes(openKey) ? prev : [...prev, openKey])
      }
    });
    return unlisten;
  }, []);

  // Initial menu expansion — 只执行一次
  useEffect(() => {
    const tmp = window.location.pathname;
    const openKey = OpenKeysMap[tmp];
    if (openKey) {
      selectedKey = tmp;
      if (openKey !== 1) {
        setOpenKeys(prev => prev.includes(openKey) ? prev : [...prev, openKey])
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
          items={menus}
          className={styles.menus}
          selectedKeys={[activeKey]}
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          onSelect={handleMenuSelect}/>
      </div>
    </Layout.Sider>
  )
}