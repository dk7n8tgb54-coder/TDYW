/**
 * 发布公告（系统管理 / 发布公告）
 * 列表 + 筛选 + 新建/编辑/发布/撤回/删除。仅全局管理员/超级管理员可访问。
 */
import React, { useState, useEffect, useCallback } from 'react';
import { observer } from 'mobx-react';
import { Breadcrumb, SearchForm, AuthDiv } from 'components';
import { Table, Button, Tag, Space, Select, Input, Radio, Popconfirm, notification } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import AnnouncementForm from './Form';
import AnnouncementDetail from './Detail';

const STATUS_TAG = {
  unpublished: { color: 'default', text: '未发布' },
  published: { color: 'green', text: '已发布' },
  expired: { color: 'red', text: '已过期' },
};

function AnnouncementAdmin() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState('');
  const [scopeType, setScopeType] = useState('');
  const [departmentId, setDepartmentId] = useState(undefined);
  const [departments, setDepartments] = useState([]);

  const [formVisible, setFormVisible] = useState(false);
  const [editing, setEditing] = useState(null);
  const [detailId, setDetailId] = useState(null);
  const [detailVisible, setDetailVisible] = useState(false);

  useEffect(() => {
    http.get('/api/home/announcement/admin/departments/')
      .then(list => setDepartments(list || []))
      .catch(() => setDepartments([]));
  }, []);

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = { page, page_size: pageSize, keyword, status, scope_type: scopeType };
    if (departmentId) params.publish_department_id = departmentId;
    http.get('/api/home/announcement/admin/', { params })
      .then(res => { setData(res.results || []); setTotal(res.total || 0); })
      .catch(() => { setData([]); setTotal(0); })
      .finally(() => setLoading(false));
  }, [page, pageSize, keyword, status, scopeType, departmentId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const doPublish = (record) => {
    http.post(`/api/home/announcement/admin/${record.id}/publish/`)
      .then(() => { notification.success({ message: '发布成功' }); fetchData(); })
      .catch(e => notification.error({ message: '发布失败', description: e.message || String(e) }));
  };

  const doWithdraw = (record) => {
    http.post(`/api/home/announcement/admin/${record.id}/withdraw/`)
      .then(() => { notification.success({ message: '已撤回' }); fetchData(); })
      .catch(e => notification.error({ message: '撤回失败', description: e.message || String(e) }));
  };

  const doDelete = (record) => {
    http.delete(`/api/home/announcement/admin/${record.id}/`)
      .then(() => { notification.success({ message: '已删除' }); fetchData(); })
      .catch(e => notification.error({ message: '删除失败', description: e.message || String(e) }));
  };

  const openCreate = () => { setEditing(null); setFormVisible(true); };
  const openEdit = (record) => {
    http.get(`/api/home/announcement/admin/${record.id}/`)
      .then(detail => { setEditing(detail); setFormVisible(true); })
      .catch(e => notification.error({ message: '加载失败', description: e.message || String(e) }));
  };
  const openDetail = (record) => { setDetailId(record.id); setDetailVisible(true); };

  const renderActions = (record) => {
    const canEdit = hasPermission('home.announcement.edit');
    const canPublish = hasPermission('home.announcement.publish');
    const canWithdraw = hasPermission('home.announcement.withdraw');
    const canDelete = hasPermission('home.announcement.delete');
    return (
      <Space>
        <a onClick={() => openDetail(record)}>详情</a>
        {canEdit && record.computed_status === 'unpublished' && <a onClick={() => openEdit(record)}>编辑</a>}
        {record.computed_status !== 'published' && canPublish && (
          <a onClick={() => doPublish(record)}>{record.computed_status === 'expired' ? '重新发布' : '发布'}</a>
        )}
        {record.computed_status === 'published' && canWithdraw && <a onClick={() => doWithdraw(record)}>撤回</a>}
        {canDelete && (
          <Popconfirm title="确定删除该公告？" onConfirm={() => doDelete(record)}>
            <a style={{ color: '#ff4d4f' }}>删除</a>
          </Popconfirm>
        )}
      </Space>
    );
  };

  const columns = [
    {
      title: '标题', dataIndex: 'title', key: 'title',
      render: (text, record) => (
        <Space size={4}>
          <a onClick={() => openDetail(record)}>{text}</a>
          {record.is_important && <Tag color="gold">重要</Tag>}
        </Space>
      ),
    },
    { title: '发布范围', dataIndex: 'scope_label', key: 'scope_label', width: 100 },
    { title: '发布部门', dataIndex: 'publish_department_name', key: 'publish_department_name', width: 140 },
    {
      title: '生效时间', key: 'effective', width: 230,
      render: (_, r) => `${r.effective_start_at || '-'}${r.effective_end_at ? ' ~ ' + r.effective_end_at : '（长期）'}`,
    },
    {
      title: '状态', dataIndex: 'computed_status', key: 'computed_status', width: 90,
      render: s => { const t = STATUS_TAG[s] || STATUS_TAG.unpublished; return <Tag color={t.color}>{t.text}</Tag>; },
    },
    { title: '发布时间', dataIndex: 'published_at', key: 'published_at', width: 160 },
    { title: '附件', dataIndex: 'attachment_count', key: 'attachment_count', width: 70 },
    { title: '操作', key: 'action', width: 200, render: (_, r) => renderActions(r) },
  ];

  return (
    <AuthDiv auth="home.announcement.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>系统管理</Breadcrumb.Item>
        <Breadcrumb.Item>发布公告</Breadcrumb.Item>
      </Breadcrumb>
      <div style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建公告</Button>
      </div>
      <SearchForm>
        <SearchForm.Item span={6} title="关键字">
          <Input allowClear value={keyword} placeholder="标题/内容" onChange={e => setKeyword(e.target.value)} />
        </SearchForm.Item>
        <SearchForm.Item span={4} title="状态">
          <Select value={status} allowClear onChange={v => setStatus(v)} placeholder="全部" style={{ width: '100%' }}>
            <Select.Option value="">全部</Select.Option>
            <Select.Option value="unpublished">未发布</Select.Option>
            <Select.Option value="published">已发布</Select.Option>
            <Select.Option value="expired">已过期</Select.Option>
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={4} title="发布范围">
          <Select value={scopeType} allowClear onChange={v => setScopeType(v)} placeholder="全部" style={{ width: '100%' }}>
            <Select.Option value="">全部</Select.Option>
            <Select.Option value="all">全平台</Select.Option>
            <Select.Option value="tenant">指定部门</Select.Option>
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={5} title="发布部门">
          <Select value={departmentId} allowClear showSearch optionFilterProp="children" onChange={v => setDepartmentId(v)} placeholder="全部" style={{ width: '100%' }}>
            {departments.map(d => <Select.Option key={d.id} value={d.id}>{d.name}</Select.Option>)}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={3} title=" ">
          <Button type="primary" onClick={() => { setPage(1); fetchData(); }}>查询</Button>
        </SearchForm.Item>
      </SearchForm>
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={{ current: page, pageSize, total, showSizeChanger: true, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }}
      />
      {formVisible && (
        <AnnouncementForm
          record={editing}
          departments={departments}
          onCancel={() => setFormVisible(false)}
          onOk={() => { setFormVisible(false); fetchData(); }}
        />
      )}
      {detailVisible && (
        <AnnouncementDetail
          announcementId={detailId}
          departments={departments}
          onClose={() => setDetailVisible(false)}
          onChanged={() => fetchData()}
        />
      )}
    </AuthDiv>
  );
}

export default observer(AnnouncementAdmin);
