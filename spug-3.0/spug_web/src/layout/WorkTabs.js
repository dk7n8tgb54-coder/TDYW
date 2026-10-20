/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 工作页签条（2026-10-19 导航改造；2026-10-20 数量上限与导航拦截）。
 *
 * 位于 Header 之下、内容区之上：左侧菜单负责打开页面，这里只负责
 * 已打开页面之间的切换。溢出滚动与"更多"下拉由 antd Tabs 内建处理。
 *
 * 导航拦截（history.block）：需要开新页签而全部候选页签均有未保存内容时，
 * 在导航发生前阻止——返回 false 使 history 取消本次跳转（PUSH 不改 URL、
 * 前进/后退自动回退），URL、侧栏选中与当前页签保持一致，并提示用户先
 * 保存或手动关闭部分页签。
 */
import React, {useEffect} from 'react';
import {Tabs, message} from 'antd';
import {observer} from 'mobx-react';
import {history} from 'libs';
import workTabStore from './workTabStore';
import styles from './layout.module.less';

// 导航切换后的短暂窗口内忽略容器滚动事件，避免内容交换时的
// clamp 滚动污染目标页签的滚动记忆
const SCROLL_SAVE_FREEZE_MS = 200;

export default observer(function WorkTabs() {
  useEffect(() => {
    workTabStore.restore(history.location);
    // 导航准入拦截：全部候选页签均有未保存内容时阻止开新页签
    const unblock = history.block(location => {
      const verdict = workTabStore.checkNavigation(location.pathname);
      if (!verdict.allowed) {
        message.warning(verdict.reason);
        return false;
      }
    });
    let lastNavigatedAt = 0;
    const saveScroll = () => {
      if (Date.now() - lastNavigatedAt < SCROLL_SAVE_FREEZE_MS) return;
      const container = document.getElementById('spug-container');
      if (container) {
        workTabStore.scrollMemory[history.location.pathname] = container.scrollTop;
      }
    };
    const unlisten = history.listen(location => {
      lastNavigatedAt = Date.now();
      workTabStore.syncLocation(location);
      // 新页面渲染后恢复该页签的滚动位置（store 缓存数据使其高度基本一致）
      requestAnimationFrame(() => {
        const container = document.getElementById('spug-container');
        if (container) container.scrollTop = workTabStore.scrollMemory[location.pathname] || 0;
      });
    });
    const container = document.getElementById('spug-container');
    if (container) container.addEventListener('scroll', saveScroll, {passive: true});
    return () => {
      unblock();
      unlisten();
      if (container) container.removeEventListener('scroll', saveScroll);
    };
  }, []);

  function handleTabChange(key) {
    const tab = workTabStore.tabs.find(item => item.key === key);
    if (tab) history.push(tab.url);
  }

  function handleEdit(targetKey, action) {
    if (action === 'remove') workTabStore.closeTab(targetKey);
  }

  return (
    <div className={styles.workTabs}>
      <Tabs
        type="editable-card"
        hideAdd
        activeKey={workTabStore.activeKey}
        onChange={handleTabChange}
        onEdit={handleEdit}>
        {workTabStore.tabs.map(tab => (
          <Tabs.TabPane key={tab.key} tab={tab.title} closable={tab.closable !== false}/>
        ))}
      </Tabs>
    </div>
  );
});
