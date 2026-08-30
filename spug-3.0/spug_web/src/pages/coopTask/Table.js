/**
 * 我发起的协作任务（发起方视角）
 */
import React, {useState, useEffect, useCallback} from 'react';
import {observer} from 'mobx-react';
import {Table, Button, Tag, Space, Input, Select, Popconfirm, notification} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {http, hasPermission} from 'libs';
import {SearchForm} from 'components';
import TaskForm from './Form';
import TaskDetail from './Detail';
import {TASK_STATUS_MAP} from './utils';
import coopTaskBadge from '@/layout/CoopTaskBadgeStore';

function TaskTable() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState('');

  const [formVisible, setFormVisible] = useState(false);
  const [editing, setEditing] = useState(null); // 编辑时传任务详情
  const [detailId, setDetailId] = useState(null);
  const [detailVisible, setDetailVisible] = useState(false);
  const [autoOpenTemplate, setAutoOpenTemplate] = useState(false); // 新建后引导上传模板

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = {page, page_size: pageSize, keyword, status};
    http.get('/api/coop-task/tasks/', {params})
      .then(res => {
        setData(res.results || []);
        setTotal(res.total || 0);
      })
      .catch(() => {
        setData([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [page, pageSize, keyword, status]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const doVoid = (record) => {
    http.post(`/api/coop-task/tasks/${record.id}/void/`)
      .then(() => {
        notification.success({message: '任务已作废'});
        fetchData();
        coopTaskBadge.fetch();
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ });
  };

  const doDelete = (record) => {
    http.delete(`/api/coop-task/tasks/${record.id}/`)
      .then(() => {
        notification.success({message: '已删除'});
        fetchData();
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ });
  };

  const openEdit = (record) => {
    http.get(`/api/coop-task/tasks/${record.id}/`)
      .then(detail => {
        setEditing(detail);
        setFormVisible(true);
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ });
  };

  const renderProgress = (_, record) => {
    const p = record.progress || {};
    return (
      <span>
        {p.accepted || 0}/{p.total || 0} 已验收
        {(p.submitted || 0) > 0 && <Tag color="blue" style={{marginLeft: 4}}>{p.submitted} 待验收</Tag>}
        {(p.rejected || 0) > 0 && <Tag color="red" style={{marginLeft: 4}}>{p.rejected} 已退回</Tag>}
      </span>
    );
  };

  const renderActions = (record) => {
    const canEdit = hasPermission('coop.task.edit');
    const canDelete = hasPermission('coop.task.delete');
    return (
      <Space>
        <a onClick={() => {
          setDetailId(record.id);
          setDetailVisible(true);
        }}>详情</a>
        {canEdit && record.status === 'in_progress' && <a onClick={() => openEdit(record)}>编辑</a>}
        {canDelete && record.status === 'in_progress' && (
          <Popconfirm title={`确定作废任务「${record.title}」？作废后交付科室无法继续提交。`}
                      onConfirm={() => doVoid(record)}>
            <a style={{color: '#faad14'}}>作废</a>
          </Popconfirm>
        )}
        {canDelete && (
          <Popconfirm title="确定删除该任务？删除后各科室不再可见。"
                      onConfirm={() => doDelete(record)}>
            <a style={{color: '#ff4d4f'}}>删除</a>
          </Popconfirm>
        )}
      </Space>
    );
  };

  const columns = [
    {
      title: '任务标题', dataIndex: 'title', key: 'title',
      render: (text, record) => (
        <a onClick={() => {
          setDetailId(record.id);
          setDetailVisible(true);
        }}>{text}</a>
      ),
    },
    {
      title: '交付对象', dataIndex: 'target_tenants', key: 'target_tenants',
      width: 200, ellipsis: true,
      render: v => (v || []).join('、'),
    },
    {title: '交付进度', key: 'progress', width: 220, render: renderProgress},
    {
      title: '截止时间', dataIndex: 'deadline', key: 'deadline', width: 150,
      render: (text, record) => (
        <Space size={4}>
          {text}
          {record.is_overdue && <Tag color="red">已逾期</Tag>}
        </Space>
      ),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: s => {
        const t = TASK_STATUS_MAP[s] || {color: 'default', text: s};
        return <Tag color={t.color}>{t.text}</Tag>;
      },
    },
    {title: '发起人', dataIndex: 'created_by_name', key: 'created_by_name', width: 100},
    {title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 140},
    {title: '操作', key: 'action', width: 200, render: (_, record) => renderActions(record)},
  ];

  return (
    <div>
      <div style={{marginBottom: 12}}>
        {hasPermission('coop.task.add') && (
          <Button type="primary" icon={<PlusOutlined/>} onClick={() => {
            setEditing(null);
            setFormVisible(true);
          }}>新建任务</Button>
        )}
      </div>
      <SearchForm>
        <SearchForm.Item span={6} title="关键字">
          <Input allowClear value={keyword} placeholder="任务标题/说明"
                 onChange={e => setKeyword(e.target.value)}/>
        </SearchForm.Item>
        <SearchForm.Item span={4} title="状态">
          <Select value={status} allowClear onChange={v => setStatus(v)} placeholder="全部"
                  style={{width: '100%'}}>
            <Select.Option value="">全部</Select.Option>
            <Select.Option value="in_progress">进行中</Select.Option>
            <Select.Option value="completed">已完成</Select.Option>
            <Select.Option value="voided">已作废</Select.Option>
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={3} title=" ">
          <Button type="primary" onClick={() => {
            setPage(1);
            fetchData();
          }}>查询</Button>
        </SearchForm.Item>
      </SearchForm>
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={{
          current: page, pageSize, total, showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />
      {formVisible && (
        <TaskForm
          record={editing}
          onCancel={() => setFormVisible(false)}
          onOk={(task) => {
            setFormVisible(false);
            // 新建成功：自动打开详情引导上传模板
            if (task && task.id) {
              setDetailId(task.id);
              setDetailVisible(true);
              setAutoOpenTemplate(true);
            }
            fetchData();
          }}
        />
      )}
      {detailVisible && (
        <TaskDetail
          taskId={detailId}
          autoOpenTemplate={autoOpenTemplate}
          onClose={() => {
            setDetailVisible(false);
            setAutoOpenTemplate(false);
          }}
          onChanged={() => {
            fetchData();
            coopTaskBadge.fetch();
          }}
        />
      )}
    </div>
  );
}

export default observer(TaskTable);
