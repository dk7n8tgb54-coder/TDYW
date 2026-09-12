/**
 * 更新日志管理（系统管理 / 更新日志）
 *
 * 列表 + 筛选 + 新建/编辑/发布/撤回/删除，权限码 system.release_note.*。
 * 「每次更新后自动弹出更新日志」为用户个人偏好（弹窗内勾选），不在管理页配置。
 */
import React, {useState, useEffect, useCallback} from 'react';
import {observer} from 'mobx-react';
import {Breadcrumb, SearchForm, AuthDiv} from 'components';
import {Table, Button, Tag, Space, Select, Input, Popconfirm, notification} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {http, hasPermission} from 'libs';
import ReleaseNoteForm from './Form';

function ReleaseNotesAdmin() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [keyword, setKeyword] = useState('');
  const [isPublished, setIsPublished] = useState('');
  const [version, setVersion] = useState('');

  const [formVisible, setFormVisible] = useState(false);
  const [editing, setEditing] = useState(null);

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = {page, page_size: pageSize, keyword, version};
    if (isPublished !== '') params.is_published = isPublished === 'true';
    http.get('/api/system/release-notes/admin/', {params})
      .then(res => {
        setData((res && res.items) || []);
        setTotal((res && res.total) || 0);
      })
      .catch(() => {
        setData([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [page, pageSize, keyword, version, isPublished]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const doPublish = (record, is_published) => {
    http.post(`/api/system/release-notes/admin/${record.id}/publish/`, {is_published})
      .then(() => {
        notification.success({message: is_published ? '发布成功' : '已撤回'});
        fetchData();
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ });
  };

  const doDelete = (record) => {
    http.delete('/api/system/release-notes/admin/', {data: {id: record.id}})
      .then(() => {
        notification.success({message: '已删除'});
        fetchData();
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ });
  };

  const openCreate = () => { setEditing(null); setFormVisible(true); };
  const openEdit = (record) => {
    http.get(`/api/system/release-notes/admin/${record.id}/`)
      .then(detail => { setEditing(detail); setFormVisible(true); })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ });
  };

  const canEdit = hasPermission('system.release_note.edit');
  const canAdd = hasPermission('system.release_note.add');
  const canPublish = hasPermission('system.release_note.publish');
  const canDelete = hasPermission('system.release_note.del');

  const columns = [
    {title: '版本', dataIndex: 'version', key: 'version', width: 110},
    {
      title: '标题', dataIndex: 'title', key: 'title',
      render: (text, record) => (
        <Space size={4}>
          <span>{text}</span>
          {record.is_required && <Tag color="red">需确认</Tag>}
        </Space>
      ),
    },
    {
      title: '状态', dataIndex: 'is_published', key: 'is_published', width: 90,
      render: p => <Tag color={p ? 'green' : 'default'}>{p ? '已发布' : '未发布'}</Tag>,
    },
    {title: '发布时间', dataIndex: 'publish_at', key: 'publish_at', width: 160},
    {
      title: '操作', key: 'action', width: 200,
      render: (_, record) => (
        <Space>
          {canEdit && <a onClick={() => openEdit(record)}>编辑</a>}
          {canPublish && (
            <a onClick={() => doPublish(record, !record.is_published)}>
              {record.is_published ? '撤回' : '发布'}
            </a>
          )}
          {canDelete && (
            <Popconfirm title="确定删除该更新日志？" onConfirm={() => doDelete(record)}>
              <a style={{color: '#ff4d4f'}}>删除</a>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <AuthDiv auth="system.release_note.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>系统管理</Breadcrumb.Item>
        <Breadcrumb.Item>更新日志</Breadcrumb.Item>
      </Breadcrumb>
      <div style={{marginBottom: 12}}>
        {canAdd && (
          <Button type="primary" icon={<PlusOutlined/>} onClick={openCreate}>新建更新日志</Button>
        )}
      </div>
      <SearchForm>
        <SearchForm.Item span={5} title="版本号">
          <Input allowClear value={version} placeholder="如 v3.3.3"
                 onChange={e => setVersion(e.target.value)}/>
        </SearchForm.Item>
        <SearchForm.Item span={5} title="关键字">
          <Input allowClear value={keyword} placeholder="标题/内容"
                 onChange={e => setKeyword(e.target.value)}/>
        </SearchForm.Item>
        <SearchForm.Item span={4} title="状态">
          <Select value={isPublished} onChange={v => setIsPublished(v)} style={{width: '100%'}}>
            <Select.Option value="">全部</Select.Option>
            <Select.Option value="true">已发布</Select.Option>
            <Select.Option value="false">未发布</Select.Option>
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
        pagination={{
          current: page, pageSize, total, showSizeChanger: true,
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }}
      />
      {formVisible && (
        <ReleaseNoteForm
          record={editing}
          onCancel={() => setFormVisible(false)}
          onOk={() => { setFormVisible(false); fetchData(); }}
        />
      )}
    </AuthDiv>
  );
}

export default observer(ReleaseNotesAdmin);
