/**
 * 协作任务（发起方 + 交付方双视角）
 *
 * 支持深链参数（供工作台等入口直达）：
 * - ?tab=tasks|inbox  指定初始页签
 * - ?task=<任务ID>    打开"我发起的"任务详情
 * - ?inbox=<分派ID>   打开"待我交付"交付详情
 */
import React, {useState, useEffect} from 'react';
import {observer} from 'mobx-react';
import {Tabs} from 'antd';
import {AuthDiv, Breadcrumb} from 'components';
import TaskTable from './Table';
import InboxTable from './InboxTable';
import InboxDetail from './InboxDetail';
import TaskDetail from './Detail';
import coopTaskBadge from '@/layout/CoopTaskBadgeStore';

function CoopTaskIndex() {
  const [activeKey, setActiveKey] = useState('tasks');
  const [inboxId, setInboxId] = useState(null); // 待我交付：当前打开的交付详情分派ID
  const [inboxRefreshKey, setInboxRefreshKey] = useState(0);
  const [detailId, setDetailId] = useState(null); // 深链直达的任务详情ID

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get('tab');
    if (tab === 'tasks' || tab === 'inbox') {
      setActiveKey(tab);
    }
    const inbox = parseInt(params.get('inbox'), 10);
    if (inbox) {
      setActiveKey('inbox');
      setInboxId(inbox);
    }
    const task = parseInt(params.get('task'), 10);
    if (task) {
      setDetailId(task);
    }
  }, []);

  // 交付详情内提交/被退回后刷新收件箱列表与角标
  const refreshInbox = () => {
    setInboxRefreshKey(k => k + 1);
    coopTaskBadge.fetch();
  };

  return (
    <AuthDiv auth="coop.task.view|coop.task.submit">
      <Breadcrumb>
        <Breadcrumb.Item>协作任务</Breadcrumb.Item>
      </Breadcrumb>
      <Tabs activeKey={activeKey} onChange={setActiveKey}>
        <Tabs.TabPane tab="我发起的" key="tasks">
          {activeKey === 'tasks' && <TaskTable/>}
        </Tabs.TabPane>
        <Tabs.TabPane tab="待我交付" key="inbox">
          {activeKey === 'inbox' && (
            <InboxTable key={inboxRefreshKey} onOpenDetail={record => setInboxId(record.id)}/>
          )}
        </Tabs.TabPane>
      </Tabs>
      {inboxId && (
        <InboxDetail
          assignmentId={inboxId}
          onClose={() => setInboxId(null)}
          onChanged={refreshInbox}
        />
      )}
      {detailId && (
        <TaskDetail
          taskId={detailId}
          onClose={() => setDetailId(null)}
          onChanged={() => coopTaskBadge.fetch()}
        />
      )}
    </AuthDiv>
  );
}

export default observer(CoopTaskIndex);
