/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Card, Button, Modal, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { http } from 'libs';
import TodoForm from './components/TodoForm';
import TodoList from './components/TodoList';

function TodoIndex() {
  const [form] = TodoForm.useForm?.() || [null];
  const [fetching, setFetching] = useState(false);
  const [loading, setLoading] = useState(false);
  const [isEdit, setIsEdit] = useState(false);
  const [isAdd, setIsAdd] = useState(false);
  const [records, setRecords] = useState([]);
  const [record, setRecord] = useState();

  useEffect(() => { fetchRecords(); }, []);

  const fetchRecords = () => {
    setFetching(true);
    http.get('/api/home/todo/')
      .then(res => setRecords(res))
      .finally(() => setFetching(false));
  };

  const handleSubmit = (formData) => {
    setLoading(true);
    http.post('/api/home/todo/', formData)
      .then(() => {
        fetchRecords();
        setRecord(null);
        setIsAdd(false);
        setIsEdit(false);
      })
      .finally(() => setLoading(false));
  };

  const handleComplete = (item) => {
    http.post('/api/home/todo/', { id: item.id, status: 'completed' })
      .then(() => { fetchRecords(); message.success('已完成'); });
  };

  const handleDelete = (item) => {
    Modal.confirm({
      title: '操作确认',
      content: `确定要删除待办事项【${item.title}】？`,
      onOk: () => http.delete('/api/home/todo/', { params: { id: item.id } }).then(fetchRecords)
    });
  };

  const showForm = (info) => {
    setRecord(info);
    setIsEdit(true);
  };

  const showAddForm = () => { setIsAdd(true); setRecord({}); };
  const handleCancel = () => { setIsAdd(false); setIsEdit(false); setRecord(null); };

  const isFormVisible = isAdd || isEdit;

  return (
    <Card
      title="待办事项"
      bodyStyle={{ height: 400, padding: '0 24px' }}
      loading={fetching}
      extra={<Button type="link" icon={<PlusOutlined />} onClick={showAddForm}>添加</Button>}
    >
      {isFormVisible ? (
        <TodoForm
          form={form}
          loading={loading}
          record={record}
          onSubmit={handleSubmit}
          onCancel={handleCancel}
        />
      ) : (
        <TodoList
          records={records}
          onEdit={showForm}
          onDelete={handleDelete}
          onComplete={handleComplete}
        />
      )}
      {records.length === 0 && !isFormVisible && (
        <div style={{ marginTop: 40, color: '#999', textAlign: 'center' }}>暂无待办事项</div>
      )}
    </Card>
  );
}

export default TodoIndex;
