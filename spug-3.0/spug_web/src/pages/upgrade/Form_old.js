/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Tabs, Upload, Image } from 'antd';
import { PlusOutlined, PlusCircleOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { X_TOKEN } from 'libs/functools';
import moment from 'moment';
import store from './store';

const { Option } = Select;
const { TabPane } = Tabs;

export default observer(function () {
  const [form] = Form.useForm();
  const [updateForm] = Form.useForm();  // 首次升级记录表单
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState(false);
  const [updatesList, setUpdatesList] = useState([]);
  const [addUpdateVisible, setAddUpdateVisible] = useState(false);
  const [editUpdateVisible, setEditUpdateVisible] = useState(false);
  const [editingUpdate, setEditingUpdate] = useState(null);
  const [imageList, setImageList] = useState([]);  // 图片列表

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();

    // 编辑时需要添加 id
    if (store.record.id) {
      formData['id'] = store.record.id;
    } else {
      // 新建时需要首次升级记录
      const updateData = updateForm.getFieldsValue();
      formData['first_update'] = updateData;

      if (updateData['update_date']) {
        updateData['update_date'] = updateData['update_date'].format('YYYY-MM-DD');
      }
      // 处理附件
      if (imageList.length > 0) {
        updateData['attachments'] = imageList;
      }
    }

    // 格式化升级时间
    if (formData.upgrade_time) {
      formData.upgrade_time = formData.upgrade_time.format('YYYY-MM-DD HH:mm:ss');
    }

    const httpMethod = store.record.id ? 'put' : 'post';

    http[httpMethod]('/api/upgrade/upgrade/', formData)
      .then(() => {
        message.success('操作成功');
        store.formVisible = false;
        store.fetchRecords();
      }, () => setLoading(false));
  }

  function handleAddUpdate() {
    const updateData = updateForm.getFieldsValue();

    if (!updateData.update_date || !updateData.recorder || !updateData.detail_content) {
      message.warning('请填写完整的升级记录信息');
      return;
    }

    const formData = {
      upgrade_id: store.record.id,
      update_date: updateData.update_date.format('YYYY-MM-DD'),
      update_time_detail: updateData.update_time_detail || '',
      recorder: updateData.recorder,
      detail_content: updateData.detail_content,
      attachments: imageList,  // 添加图片附件
    };

    http.post('/api/upgrade/upgrade/update/', formData)
      .then(() => {
        message.success('升级记录添加成功');
        updateForm.resetFields();
        setImageList([]);  // 清空图片列表
        setAddUpdateVisible(false);
        fetchUpdates();
        store.fetchRecords();
      });
  }

  function handleEditUpdate(update) {
    // 打开编辑弹窗，填充现有数据
    setEditingUpdate(update);
    setImageList(update.attachments || []);
    updateForm.setFieldsValue({
      update_date: moment(update.update_date),
      update_time_detail: update.update_time_detail || '',
      recorder: update.recorder,
      detail_content: update.detail_content,
    });
    setEditUpdateVisible(true);
  }

  function handleDeleteUpdate(update) {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${update.update_date}】的升级记录?`,
      onOk: () => {
        return http.delete('/api/upgrade/upgrade/update/', {params: {id: update.id}})
          .then(() => {
            message.success('删除成功');
            fetchUpdates();
            store.fetchRecords();
          });
      }
    });
  }

  function handleUpdateUpdate() {
    const updateData = updateForm.getFieldsValue();

    if (!updateData.update_date || !updateData.recorder || !updateData.detail_content) {
      message.warning('请填写完整的升级记录信息');
      return;
    }

    const formData = {
      id: editingUpdate.id,
      update_date: updateData.update_date.format('YYYY-MM-DD'),
      update_time_detail: updateData.update_time_detail || '',
      recorder: updateData.recorder,
      detail_content: updateData.detail_content,
      attachments: imageList,
    };

    http.put('/api/upgrade/upgrade/update/', formData)
      .then(() => {
        message.success('升级记录更新成功');
        updateForm.resetFields();
        setImageList([]);
        setEditUpdateVisible(false);
        setEditingUpdate(null);
        fetchUpdates();
        store.fetchRecords();
      });
  }

  // 图片上传处理
  const uploadProps = {
    name: 'file',
    action: '/api/runlog/upload/',  // 使用运行日志的上传接口
    accept: 'image/*',
    listType: 'picture-card',
    headers: {
      'X-Token': X_TOKEN,
    },
    fileList: imageList.map((url, index) => ({
      uid: `-${index}`,
      name: `image-${index}.png`,
      status: 'done',
      url: url,
    })),
    onChange: (info) => {
      if (info.file.status === 'done') {
        const newUrl = info.file.response?.url;
        if (newUrl) {
          setImageList(prev => [...prev, newUrl]);
          message.success('图片上传成功');
        } else {
          message.error('上传响应中没有URL');
        }
      } else if (info.file.status === 'error') {
        message.error(`图片上传失败: ${info.file.response?.error || '未知错误'}`);
      }
    },
    beforeUpload: (file) => {
      const isImage = file.type.startsWith('image/');
      if (!isImage) {
        message.error('只能上传图片文件');
        return false;
      }
      const isLt10M = file.size / 1024 / 1024 < 10;
      if (!isLt10M) {
        message.error('图片大小不能超过10MB');
        return false;
      }
      return true;
    },
    onRemove: (file) => {
      setImageList(prev => prev.filter(url => url !== file.url));
    },
  };

  function fetchUpdates() {
    if (store.record.id) {
      http.get('/api/upgrade/upgrade/update/', {params: {upgrade_id: store.record.id}})
        .then(res => {
          setUpdatesList(res.updates || []);
        });
    }
  }

  useEffect(() => {
    if (store.record.id) {
      fetchUpdates();  // 编辑模式下加载升级记录列表
      if (store.record.isViewMode || !hasPermission('upgrade.upgrade.edit')) {
        setViewMode(true);
      } else {
        setViewMode(false);
      }
      // 如果是添加升级记录模式，直接打开添加弹窗
      if (store.record.isAddUpdateMode) {
        setAddUpdateVisible(true);
      }
    }
  }, [store.record.id]);

  const info = store.record;

  // 查看模式
  if (viewMode) {
    return (
      <Modal
        visible
        width={900}
        title="升级表单详情"
        footer={[
          <Button key="close" onClick={() => store.formVisible = false}>关闭</Button>
        ]}
        onCancel={() => store.formVisible = false}>
        <Tabs defaultActiveKey="basic">
          <TabPane tab="基本信息" key="basic">
            <div style={{ padding: '0 0 16px 0' }}>
              <div><strong>升级单号：</strong>{info.upgrade_no}</div>
              <div><strong>系统：</strong>{info.system}</div>
              <div><strong>升级类型：</strong>{info.upgrade_type}</div>
              <div><strong>版本：</strong>{info.version}</div>
              <div><strong>升级时间：</strong>{info.upgrade_time}</div>
              <div><strong>状态：</strong>{info.status}</div>
              <div><strong>负责人：</strong>{info.owner}</div>
            </div>
          </TabPane>
          <TabPane tab="升级记录" key="updates">
            {updatesList.map(update => (
              <div key={update.id} style={{
                marginBottom: 12,
                padding: 12,
                border: '1px solid #e8e8e8',
                borderRadius: 4
              }}>
                <div><strong>{update.update_date} [序号{update.sequence}] {update.recorder}</strong></div>
                <div style={{ whiteSpace: 'pre-wrap', marginTop: 8 }}>{update.detail_content}</div>
                {update.update_time_detail && (
                  <div style={{ color: '#999', fontSize: 12 }}>{update.update_time_detail}</div>
                )}
                {/* 显示附件图片 */}
                {update.attachments && update.attachments.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>附件：</div>
                    <Image.PreviewGroup>
                      {update.attachments.map((img, idx) => (
                        <Image
                          key={idx}
                          src={img}
                          width={100}
                          height={100}
                          style={{ objectFit: 'cover', marginRight: 8, marginBottom: 8 }}
                        />
                      ))}
                    </Image.PreviewGroup>
                  </div>
                )}
              </div>
            ))}
            {updatesList.length === 0 && <div style={{ textAlign: 'center', color: '#999' }}>暂无升级记录</div>}
          </TabPane>
        </Tabs>
      </Modal>
    );
  }

  // 编辑/新建模式
  const initialValues = {...info};
  if (initialValues.upgrade_time) {
    initialValues.upgrade_time = moment(initialValues.upgrade_time);
  }

  const updateInitialValues = {};
  if (!store.record.id) {
    // 新建时初始化首次升级记录
    updateInitialValues.update_date = moment();
    updateInitialValues.recorder = localStorage.getItem('username') || '';
  }

  return (
    <Modal
      visible
      width={900}
      maskClosable={false}
      title={store.record.id ? '编辑升级表单' : '新建升级表单'}
      onCancel={() => store.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Tabs defaultActiveKey="basic">
        <TabPane tab="基本信息" key="basic">
          <Form form={form} initialValues={initialValues} labelCol={{span: 5}} wrapperCol={{span: 14}}>
            <Form.Item required name="upgrade_no" label="升级单号" rules={[{required: true, message: '请输入升级单号'}]}>
              <Input placeholder="请输入升级单号"/>
            </Form.Item>
            <Form.Item required name="system" label="系统" rules={[{required: true, message: '请输入系统'}]}>
              <Input placeholder="请输入系统"/>
            </Form.Item>
            <Form.Item required name="upgrade_type" label="升级类型" rules={[{required: true, message: '请选择升级类型'}]}>
              <Select placeholder="请选择升级类型">
                <Option value="功能升级">功能升级</Option>
                <Option value="Bug修复">Bug修复</Option>
                <Option value="安全补丁">安全补丁</Option>
                <Option value="性能优化">性能优化</Option>
              </Select>
            </Form.Item>
            <Form.Item required name="version" label="版本" rules={[{required: true, message: '请输入版本'}]}>
              <Input placeholder="请输入版本"/>
            </Form.Item>
            <Form.Item required name="upgrade_time" label="升级时间" rules={[{required: true, message: '请选择升级时间'}]}>
              <DatePicker showTime style={{width: '100%'}} placeholder="请选择升级时间"/>
            </Form.Item>
            <Form.Item required name="status" label="状态" rules={[{required: true, message: '请选择状态'}]}>
              <Select placeholder="请选择状态">
                <Option value="待处理">待处理</Option>
                <Option value="进行中">进行中</Option>
                <Option value="已完成">已完成</Option>
                <Option value="已取消">已取消</Option>
              </Select>
            </Form.Item>
            <Form.Item required name="owner" label="负责人" rules={[{required: true, message: '请输入负责人'}]}>
              <Input placeholder="请输入负责人"/>
            </Form.Item>
          </Form>

          {!store.record.id && (
            <div style={{ marginTop: 16, padding: 16, backgroundColor: '#f5f5f5', borderRadius: 4 }}>
              <h4>首次升级记录（必填）</h4>
              <Form form={updateForm} initialValues={updateInitialValues} labelCol={{span: 5}} wrapperCol={{span: 14}}>
                <Form.Item required name="update_date" label="记录日期" rules={[{required: true, message: '请选择日期'}]}>
                  <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
                </Form.Item>
                <Form.Item name="update_time_detail" label="时间详情">
                  <Input placeholder="时间详情，如：14:00开始升级（选填）"/>
                </Form.Item>
                <Form.Item required name="recorder" label="记录人" rules={[{required: true, message: '请输入记录人'}]}>
                  <Input placeholder="请输入记录人"/>
                </Form.Item>
                <Form.Item required name="detail_content" label="详细记录" rules={[{required: true, message: '请输入详细记录'}]}>
                  <Input.TextArea rows={6} placeholder="请输入详细记录"/>
                </Form.Item>
                <Form.Item label="图片附件">
                  <Upload {...uploadProps}>
                    <div>
                      <PlusCircleOutlined />
                      <div style={{ marginTop: 8 }}>上传图片</div>
                    </div>
                  </Upload>
                  <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                    支持JPG、PNG、GIF、WebP格式，单个文件最大10MB
                  </div>
                </Form.Item>
              </Form>
            </div>
          )}
        </TabPane>

        {store.record.id && (
          <TabPane tab="升级记录" key="updates">
            <div style={{ marginBottom: 16 }}>
              <Button type="primary" icon={<PlusOutlined/>} onClick={() => setAddUpdateVisible(true)}>
                添加升级记录
              </Button>
            </div>
            {updatesList.map(update => (
              <div key={update.id} style={{
                marginBottom: 12,
                padding: 12,
                border: '1px solid #e8e8e8',
                borderRadius: 4
              }}>
                <div>
                  <strong>{update.update_date} [序号{update.sequence}] {update.recorder}</strong>
                  {update.can_edit && (
                    <span
                      style={{ marginLeft: 8, color: '#1890ff', cursor: 'pointer' }}
                      onClick={() => handleEditUpdate(update)}
                    >
                      [可编辑]
                    </span>
                  )}
                  {hasPermission('upgrade.upgrade.update_del') && (
                    <span
                      style={{ marginLeft: 8, color: '#ff4d4f', cursor: 'pointer' }}
                      onClick={() => handleDeleteUpdate(update)}
                    >
                      [删除]
                    </span>
                  )}
                </div>
                <div style={{ whiteSpace: 'pre-wrap', marginTop: 8 }}>{update.detail_content}</div>
                {update.update_time_detail && (
                  <div style={{ color: '#999', fontSize: 12 }}>{update.update_time_detail}</div>
                )}
                {/* 显示附件图片 */}
                {update.attachments && update.attachments.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>附件：</div>
                    <Image.PreviewGroup>
                      {update.attachments.map((img, idx) => (
                        <Image
                          key={idx}
                          src={img}
                          width={100}
                          height={100}
                          style={{ objectFit: 'cover', marginRight: 8, marginBottom: 8 }}
                        />
                      ))}
                    </Image.PreviewGroup>
                  </div>
                )}
              </div>
            ))}
            {updatesList.length === 0 && <div style={{ textAlign: 'center', color: '#999' }}>暂无升级记录</div>}
          </TabPane>
        )}
      </Tabs>

      {/* 添加升级记录的弹窗 */}
      {addUpdateVisible && (
        <Modal
          title="添加升级记录"
          visible={addUpdateVisible}
          onCancel={() => {
            setAddUpdateVisible(false);
            setImageList([]);
          }}
          onOk={handleAddUpdate}
          okText="添加"
          cancelText="取消"
          width={700}>
          <Form form={updateForm} labelCol={{span: 5}} wrapperCol={{span: 19}}>
            <Form.Item required name="update_date" label="记录日期" rules={[{required: true, message: '请选择日期'}]}>
              <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
            </Form.Item>
            <Form.Item name="update_time_detail" label="时间详情">
              <Input placeholder="时间详情，如：14:00开始升级（选填）"/>
            </Form.Item>
            <Form.Item required name="recorder" label="记录人" rules={[{required: true, message: '请输入记录人'}]}>
              <Input placeholder="请输入记录人"/>
            </Form.Item>
            <Form.Item required name="detail_content" label="详细记录" rules={[{required: true, message: '请输入详细记录'}]}>
              <Input.TextArea rows={4} placeholder="请输入详细记录"/>
            </Form.Item>
            <Form.Item label="图片附件">
              <Upload {...uploadProps}>
                <div>
                  <PlusCircleOutlined />
                  <div style={{ marginTop: 8 }}>上传图片</div>
                </div>
              </Upload>
              <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                支持JPG、PNG、GIF、WebP格式，单个文件最大10MB
              </div>
            </Form.Item>
          </Form>
        </Modal>
      )}

      {/* 编辑升级记录的弹窗 */}
      {editUpdateVisible && (
        <Modal
          title="编辑升级记录"
          visible={editUpdateVisible}
          onCancel={() => {
            setEditUpdateVisible(false);
            setImageList([]);
            setEditingUpdate(null);
          }}
          onOk={handleUpdateUpdate}
          okText="保存"
          cancelText="取消"
          width={700}>
          <Form form={updateForm} labelCol={{span: 5}} wrapperCol={{span: 19}}>
            <Form.Item required name="update_date" label="记录日期" rules={[{required: true, message: '请选择日期'}]}>
              <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
            </Form.Item>
            <Form.Item name="update_time_detail" label="时间详情">
              <Input placeholder="时间详情，如：14:00开始升级（选填）"/>
            </Form.Item>
            <Form.Item required name="recorder" label="记录人" rules={[{required: true, message: '请输入记录人'}]}>
              <Input placeholder="请输入记录人"/>
            </Form.Item>
            <Form.Item required name="detail_content" label="详细记录" rules={[{required: true, message: '请输入详细记录'}]}>
              <Input.TextArea rows={4} placeholder="请输入详细记录"/>
            </Form.Item>
            <Form.Item label="图片附件">
              <Upload {...uploadProps}>
                <div>
                  <PlusCircleOutlined />
                  <div style={{ marginTop: 8 }}>上传图片</div>
                </div>
              </Upload>
              <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                支持JPG、PNG、GIF、WebP格式，单个文件最大10MB
              </div>
            </Form.Item>
          </Form>
        </Modal>
      )}
    </Modal>
  );
});
