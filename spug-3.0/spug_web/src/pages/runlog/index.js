/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import EventTypeModal from './EventTypeModal';
import store from './store';
import { http } from 'libs';
import { useLocation } from 'react-router-dom';

export default observer(function () {
  const location = useLocation();

  // 监听URL参数，查看是否有view参数（从待办菜单跳转过来）
  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    const viewId = searchParams.get('view');
    if (viewId) {
      // 获取事件详情并打开查看弹窗
      http.get('/api/runlog/detail/', { params: { id: viewId } })
        .then(res => {
          // json_response 返回结构是 {data: {...}, error: ""}，需要访问 res.data
          store.showForm(res.data || res, true); // true表示查看模式
        })
        .catch(e => {
          console.error('[跨日事项跟踪] 获取事件详情失败:', e);
        });
    }
  }, [location.search]);

  return (
    <AuthDiv auth="runlog.runlog.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>跨日事项跟踪</Breadcrumb.Item>
      </Breadcrumb>
      <ComTable/>
      {store.formVisible && <ComForm/>}
      <EventTypeModal />
    </AuthDiv>
  );
})
