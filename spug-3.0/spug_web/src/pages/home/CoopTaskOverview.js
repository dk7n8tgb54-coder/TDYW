/**
 * 工作台协作任务面板
 *
 * 左右两栏同时展示"我发起的"（进行中任务的验收进度）与"待我交付"（本科室待处理材料），
 * 点击条目直接打开协作任务模块对应详情；无 coop.task.view 权限的用户不渲染本面板。
 */
import React, { useState, useEffect } from 'react';
import { Card, Row, Col, Tag, Badge, Progress } from 'antd';
import { TeamOutlined, SendOutlined, InboxOutlined } from '@ant-design/icons';
import { http, history, hasPermission } from 'libs';
import { ASSIGNMENT_STATUS_MAP } from '../coopTask/utils';
import styles from './index.module.less';

// 需要交付方处理的分派聚合状态（待交付/部分交付/待重新交付）
const ACTIONABLE_STATUS = ['pending', 'partial', 'rejected'];
const MAX_ROWS = 5;

function CoopTaskOverview() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [tasks, setTasks] = useState([]);
  const [inbox, setInbox] = useState([]);

  useEffect(() => {
    if (!hasPermission('coop.task.view')) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    Promise.all([
      http.get('/api/coop-task/tasks/', { params: { status: 'in_progress', page: 1, page_size: 50 } }),
      http.get('/api/coop-task/inbox/'),
    ]).then(([taskRes, inboxList]) => {
      if (cancelled) return;
      setTasks(taskRes.results || []);
      const actionable = (inboxList || [])
        .filter(x => x.task_status === 'in_progress' && ACTIONABLE_STATUS.includes(x.aggregate_status))
        .sort((a, b) => (a.deadline || '9999').localeCompare(b.deadline || '9999'));
      setInbox(actionable);
    }).catch(() => {
      if (!cancelled) setError(true);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  if (!hasPermission('coop.task.view')) return null;

  const renderEmpty = text => (
    <div style={{ color: '#999', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>{text}</div>
  );

  // 我发起的：标题行 + 验收进度条（与协作任务模块"交付进度"口径一致）
  const renderTaskItem = item => {
    const p = item.progress || {};
    const percent = p.total ? Math.round((p.accepted / p.total) * 100) : 0;
    return (
      <div
        key={item.id}
        className={styles.itemRow}
        onClick={() => history.push(`/coop-task?tab=tasks&task=${item.id}`)}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span title={item.title} className={styles.itemTitle}>{item.title}</span>
          {item.is_overdue
            ? <Tag color="red" style={{ marginRight: 0 }}>已逾期</Tag>
            : <span className={styles.itemDeadline}>{item.deadline}</span>}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', marginTop: 4 }}>
          <Progress
            percent={percent}
            size="small"
            showInfo={false}
            strokeColor={percent >= 100 ? '#52c41a' : '#1890ff'}
            style={{ flex: 1, margin: 0, marginRight: 8 }}
          />
          <span style={{ fontSize: 12, color: '#595959', whiteSpace: 'nowrap' }}>
            {p.accepted || 0}/{p.total || 0} 已验收
          </span>
          {(p.submitted || 0) > 0 && <Tag color="blue" style={{ marginLeft: 4 }}>待验收 {p.submitted}</Tag>}
          {(p.rejected || 0) > 0 && <Tag color="red" style={{ marginLeft: 4 }}>已退回 {p.rejected}</Tag>}
        </div>
      </div>
    );
  };

  // 待我交付：催办红点 + 聚合状态 + 截止时间
  const renderInboxItem = item => {
    const status = ASSIGNMENT_STATUS_MAP[item.aggregate_status] || { color: 'default', text: item.aggregate_status };
    return (
      <div
        key={item.id}
        className={styles.itemRow}
        onClick={() => history.push(`/coop-task?tab=inbox&inbox=${item.id}`)}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Badge dot={item.has_unread_urge} offset={[2, 0]}>
            <span title={item.task_title} className={styles.itemTitle}>{item.task_title}</span>
          </Badge>
          <Tag color={status.color} style={{ marginRight: 0 }}>{status.text}</Tag>
        </div>
        <div style={{ fontSize: 12, color: '#999', marginTop: 4, paddingLeft: 2 }}>
          {item.created_by_name ? `发起人：${item.created_by_name}` : ''}
          {item.created_by_name && item.deadline ? ' · ' : ''}
          {item.deadline ? `截止 ${item.deadline}` : ''}
          {item.is_overdue && <Tag color="red" style={{ marginLeft: 4 }}>已逾期</Tag>}
        </div>
      </div>
    );
  };

  const sectionHeader = (icon, title, count, countText, moreTo) => (
    <div className={styles.sectionHeader}>
      <span className={styles.sectionTitle}>{icon}{title}</span>
      <Tag color={count > 0 ? 'orange' : 'default'} style={{ marginLeft: 8 }}>
        {countText} {count}
      </Tag>
      <a className={styles.sectionLink} onClick={() => history.push(moreTo)}>全部</a>
    </div>
  );

  return (
    <Card
      title={<span><TeamOutlined style={{ marginRight: 8 }} />协作任务</span>}
      loading={loading}
      className={styles.coopPanel}
      style={{ marginBottom: 12 }}
    >
      {error ? (
        <div style={{ color: '#999', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>
          协作任务数据暂时无法获取
        </div>
      ) : (
        <Row gutter={24}>
          <Col span={12}>
            {sectionHeader(
              <SendOutlined style={{ marginRight: 6, color: '#1890ff' }} />, '我发起的',
              tasks.length, '进行中', '/coop-task?tab=tasks')}
            {tasks.length === 0 ? renderEmpty('暂无进行中的任务') : tasks.slice(0, MAX_ROWS).map(renderTaskItem)}
          </Col>
          <Col span={12} className={styles.dividerCol}>
            {sectionHeader(
              <InboxOutlined style={{ marginRight: 6, color: '#faad14' }} />, '待我交付',
              inbox.length, '待处理', '/coop-task?tab=inbox')}
            {inbox.length === 0 ? renderEmpty('暂无待交付的材料') : inbox.slice(0, MAX_ROWS).map(renderInboxItem)}
          </Col>
        </Row>
      )}
    </Card>
  );
}

export default CoopTaskOverview;
