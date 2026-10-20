/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 页面未保存内容登记 hook（2026-10-20 工作页签数量上限配套）。
 *
 * 页面在"存在未保存内容"时调用（如 excelStore.hasUnsaved、editorDirty）：
 * dirty 为真期间当前页签不参与自动淘汰；全部候选页签均有未保存内容时，
 * 打开新页签的导航会被 WorkTabs 阻止并提示。
 *
 * - 页签身份即当前路由 pathname，直接取全局 history（与页签机制同源），
 *   不依赖 Router 上下文；假定声明期间页面 pathname 不变（当前接入页面
 *   均满足：声明状态由路由内组件持有，路由切换即卸载并撤销登记）。
 * - 同一页面多处来源（如列表页自身的详情 Store 与翻阅视图的独立 Store）
 *   由 workTabStore 按来源计数合并，任一来源声明即视为有未保存内容。
 * - dirty 变化或组件卸载时自动撤销登记，不留残留。
 */
import {useEffect} from 'react';
import {history} from 'libs';
import workTabStore from './workTabStore';

export default function useWorkTabUnsaved(dirty) {
  useEffect(() => {
    const pathname = history.location && history.location.pathname;
    if (!dirty || !pathname) return undefined;
    return workTabStore.addUnsavedSource(pathname);
  }, [dirty]);
}
