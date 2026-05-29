/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Descriptions, Tabs, Upload, Image, Card } from 'antd';
import { PlusOutlined, PlusCircleOutlined, CloseOutlined, EditOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { X_TOKEN } from 'libs/functools';
import moment from 'moment';
import S from './store';

const { Option } = Select;
const { TabPane } = Tabs;

export default observer(function () {
  const [form] = Form.useForm();
  const [updateForm] = Form.useForm();  // 首次动态表单
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState(false);
  const [updatesList, setUpdatesList] = useState([]);
  const [addUpdateVisible, setAddUpdateVisible] = useState(false);
  const [editUpdateVisible, setEditUpdateVisible] = useState(false);
  const [editingUpdate, setEditingUpdate] = useState(null);
  const [imageList, setImageList] = useState([]);  // 图片列表
  const [uploading, setUploading] = useState(false);  // 上传状态

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();
    
    // 编辑时需要添加 id
    if (S.record.id) {
      formData['id'] = S.record.id;
    } else {
      // 新建时需要首次动态
      const updateData = updateForm.getFieldsValue();
      formData['first_update'] = updateData;

      if (updateData['update_date']) {
        updateData['update_date'] = updateData['update_date'].format('YYYY-MM-DD');
      }
    }

    const apiUrl = S.record.id ? '/api/runlog/' : '/api/runlog/';
    const httpMethod = S.record.id ? 'put' : 'post';

    http[httpMethod](apiUrl, formData)
      .then(() => {
        message.success('操作成功');
        S.formVisible = false;
        S.fetchRecords()
        S.fetchStatistics()
      }, () => setLoading(false))
  }

  function handleAddUpdate() {
    const updateData = updateForm.getFieldsValue();

    if (!updateData.update_date || !updateData.detail_content) {
      message.warning('请填写完整的动态信息');
      return;
    }

    const formData = {
      runlog_id: S.record.id,
      update_date: updateData.update_date.format('YYYY-MM-DD'),
      recorder: localStorage.getItem('nickname') || '',
      detail_content: updateData.detail_content,
      attachments: imageList,  // 添加图片附件
    };

    http.post('/api/runlog/update/', formData)
      .then(() => {
        message.success('动态添加成功');
        updateForm.resetFields();
        setImageList([]);  // 清空图片列表
        setAddUpdateVisible(false);
        fetchUpdates();
        S.fetchRecords();
      });
  }

  function handleEditUpdate(update) {
    // 打开编辑弹窗，填充现有数据
    setEditingUpdate(update);
    setImageList(update.attachments || []);
    updateForm.setFieldsValue({
      update_date: moment(update.update_date),
      recorder: update.recorder,
      detail_content: update.detail_content,
    });
    setEditUpdateVisible(true);
  }

  function handleDeleteUpdate(update) {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${update.update_date}】的动态记录?`,
      onOk: () => {
        return http.delete('/api/runlog/update/', {params: {id: update.id}})
          .then(() => {
            message.success('删除成功');
            fetchUpdates();
            S.fetchRecords();
            S.fetchStatistics();
          })
      }
    })
  }

  function handleUpdateUpdate() {
    const updateData = updateForm.getFieldsValue();

    if (!updateData.update_date || !updateData.detail_content) {
      message.warning('请填写完整的动态信息');
      return;
    }

    const formData = {
      id: editingUpdate.id,
      runlog_id: S.record.id,
      update_date: updateData.update_date.format('YYYY-MM-DD'),
      recorder: localStorage.getItem('nickname') || '',
      detail_content: updateData.detail_content,
      attachments: imageList,
    };

    http.put('/api/runlog/update/', formData)
      .then(() => {
        message.success('动态更新成功');
        updateForm.resetFields();
        setImageList([]);
        setEditUpdateVisible(false);
        setEditingUpdate(null);
        fetchUpdates();
        S.fetchRecords();
      });
  }

  // 图片上传处理
  const uploadProps = {
    name: 'file',
    action: '/api/runlog/upload/',
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
      console.log('Upload onChange:', info.file, info.fileList);
      if (info.file.status === 'done') {
        console.log('Upload success response:', info.file.response);
        const newUrl = info.file.response?.url;
        if (newUrl) {
          setImageList(prev => [...prev, newUrl]);
          message.success('图片上传成功');
        } else {
          message.error('上传响应中没有URL');
        }
      } else if (info.file.status === 'error') {
        console.log('Upload error:', info.file);
        message.error(`图片上传失败: ${info.file.response?.error || '未知错误'}`);
      }
    },
    beforeUpload: (file) => {
      console.log('Before upload:', file.name, file.type, file.size);
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
    if (S.record.id) {
      http.get('/api/runlog/detail/', {params: {id: S.record.id}})
        .then(res => {
          setUpdatesList(res.updates || []);
        });
    }
  }

  useEffect(() => {
    if (S.record.id) {
      fetchUpdates();  // 编辑模式下也需要加载动态列表
      if (S.record.isViewMode || !hasPermission('runlog.runlog.edit')) {
        setViewMode(true);
      } else {
        setViewMode(false);
      }
      // 如果是添加动态模式，直接打开添加动态弹窗
      if (S.record.isAddUpdateMode) {
        setAddUpdateVisible(true);
      }
    }
  }, [S.record.id]);

  const info = S.record;

  // 查看模式
  if (viewMode) {
    return (
      <Modal
        visible
        width={900}
        title="运行日志详情"
        footer={[
          <Button key="close" onClick={() => S.formVisible = false}>关闭</Button>
        ]}
        onCancel={() => S.formVisible = false}>
        <Descriptions bordered column={1}>
          <Descriptions.Item label="事件标题">{info.event_title}</Descriptions.Item>
          <Descriptions.Item label="事件类型">{info.event_type}</Descriptions.Item>
          <Descriptions.Item label="事件级别">{info.severity}</Descriptions.Item>
          <Descriptions.Item label="状态">{info.status_text}</Descriptions.Item>
          <Descriptions.Item label="系统名称">{info.system_name}</Descriptions.Item>
          <Descriptions.Item label="责任人">{info.responsible_user_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="处理措施">
            <div style={{ whiteSpace: 'pre-wrap' }}>
              {info.resolution || '-'}
            </div>
          </Descriptions.Item>
          <Descriptions.Item label="动态记录">
            {updatesList.map(update => (
              <div key={update.id} style={{
                marginBottom: 12,
                padding: 8,
                border: '1px solid #e8e8e8',
                borderRadius: 4
              }}>
                <div><strong>{update.update_date} [{update.sequence}] {update.recorder}</strong></div>
                <div>{update.detail_content}</div>
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
          </Descriptions.Item>
        </Descriptions>
      </Modal>
    )
  }

  // 编辑/新建模式
  const initialValues = {...info};
  if (initialValues.deadline) {
    initialValues.deadline = moment(initialValues.deadline);
  }
  
  const updateInitialValues = {};
  if (!S.record.id) {
    // 新建时初始化首次动态
    updateInitialValues.update_date = moment();
    updateInitialValues.recorder = localStorage.getItem('nickname') || '';
  }

  return (
    <Modal
      visible
      width={900}
      maskClosable={false}
      title={S.record.id ? '编辑运行日志' : '新建运行日志'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Tabs defaultActiveKey={S.record.isAddUpdateMode ? "updates" : "event"}>
        <TabPane tab="事件信息" key="event">
          <Form form={form} initialValues={initialValues} labelCol={{span: 5}} wrapperCol={{span: 14}}>
            <Form.Item required name="event_title" label="事件标题">
              <Input placeholder="请输入事件标题"/>
            </Form.Item>
            <Form.Item required name="event_type" label="事件类型">
              <Select placeholder="请选择事件类型">
                <Option value="运行异常">运行异常</Option>
                <Option value="设备故障">设备故障</Option>
                <Option value="安全事件">安全事件</Option>
                <Option value="其他">其他</Option>
              </Select>
            </Form.Item>
            <Form.Item required name="system_name" label="系统名称">
              <Input placeholder="请输入系统名称"/>
            </Form.Item>
            <Form.Item required name="severity" label="事件级别">
              <Select placeholder="请选择事件级别">
                <Option value="P0">P0-紧急</Option>
                <Option value="P1">P1-重要</Option>
                <Option value="P2">P2-一般</Option>
              </Select>
            </Form.Item>
            <Form.Item name="responsible_user_name" label="责任人">
              <Input placeholder="请输入责任人（选填）"/>
            </Form.Item>
            {S.record.id && (
              <>
                <Form.Item name="status" label="处理状态">
                  <Select placeholder="请选择状态">
                    <Option value="in_progress">处理中</Option>
                    <Option value="resolved">已解决</Option>
                  </Select>
                </Form.Item>
                <Form.Item name="resolution" label="处理措施">
                  <Input.TextArea rows={4} placeholder="事件解决后的最终方案总结，与动态记录不同，此处填写结案报告"/>
                </Form.Item>
              </>
            )}
          </Form>
          
          {!S.record.id && (
            <div style={{ marginTop: 16, padding: 16, backgroundColor: '#f5f5f5', borderRadius: 4 }}>
              <h4>首次动态（必填）</h4>
              <Form form={updateForm} initialValues={updateInitialValues} labelCol={{span: 5}} wrapperCol={{span: 14}}>
                <Form.Item required name="update_date" label="动态日期">
                  <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
                </Form.Item>
                <Form.Item required name="recorder" label="记录人">
                  <Input disabled placeholder="自动填充当前用户"/>
                </Form.Item>
                <Form.Item required name="detail_content" label="详细记录">
                  <Input.TextArea rows={6} placeholder="请输入详细记录"/>
                </Form.Item>
              </Form>
            </div>
          )}
        </TabPane>
        
        {S.record.id && (
          <TabPane tab="动态记录" key="updates">
            <div style={{ marginBottom: 16 }}>
              {!addUpdateVisible && !editUpdateVisible && (
                <Button type="primary" icon={<PlusOutlined/>} onClick={() => {
                  updateForm.resetFields();
                  updateForm.setFieldsValue({
                    update_date: moment(),
                    recorder: localStorage.getItem('nickname') || ''
                  });
                  setImageList([]);
                  setAddUpdateVisible(true);
                }}>
                  添加动态
                </Button>
              )}
            </div>

            {/* 内联添加动态表单 */}
            {addUpdateVisible && (
              <Card size="small" title="添加动态" style={{ marginBottom: 16 }} extra={
                <Button type="link" icon={<CloseOutlined/>} onClick={() => { setAddUpdateVisible(false); setImageList([]); }}/>
              }>
                <Form form={updateForm} initialValues={{ update_date: moment(), recorder: localStorage.getItem('nickname') || '' }} labelCol={{span: 4}} wrapperCol={{span: 20}}>
                  <Form.Item required name="update_date" label="动态日期">
                    <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
                  </Form.Item>
                  <Form.Item required name="recorder" label="记录人">
                    <Input disabled placeholder="自动填充当前用户"/>
                  </Form.Item>
                  <Form.Item required name="detail_content" label="详细记录">
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
                  <Form.Item wrapperCol={{offset: 4, span: 20}}>
                    <Button type="primary" onClick={handleAddUpdate}>提交</Button>
                    <Button style={{ marginLeft: 8 }} onClick={() => { setAddUpdateVisible(false); setImageList([]); }}>取消</Button>
                  </Form.Item>
                </Form>
              </Card>
            )}

            {/* 内联编辑动态表单 */}
            {editUpdateVisible && (
              <Card size="small" title="编辑动态" style={{ marginBottom: 16 }} extra={
                <Button type="link" icon={<CloseOutlined/>} onClick={() => { setEditUpdateVisible(false); setImageList([]); setEditingUpdate(null); }}/>
              }>
                <Form form={updateForm} initialValues={{ recorder: localStorage.getItem('nickname') || '' }} labelCol={{span: 4}} wrapperCol={{span: 20}}>
                  <Form.Item required name="update_date" label="动态日期">
                    <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
                  </Form.Item>
                  <Form.Item required name="recorder" label="记录人">
                    <Input disabled placeholder="自动填充当前用户"/>
                  </Form.Item>
                  <Form.Item required name="detail_content" label="详细记录">
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
                  <Form.Item wrapperCol={{offset: 4, span: 20}}>
                    <Button type="primary" onClick={handleUpdateUpdate}>保存</Button>
                    <Button style={{ marginLeft: 8 }} onClick={() => { setEditUpdateVisible(false); setImageList([]); setEditingUpdate(null); }}>取消</Button>
                  </Form.Item>
                </Form>
              </Card>
            )}

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
                  {hasPermission('runlog.runlog.update_del') && (
                    <span
                      style={{ marginLeft: 8, color: '#ff4d4f', cursor: 'pointer' }}
                      onClick={() => handleDeleteUpdate(update)}
                    >
                      [删除]
                    </span>
                  )}
                </div>
                <div>{update.detail_content}</div>
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
            {updatesList.length === 0 && <div style={{ textAlign: 'center', color: '#999' }}>暂无动态记录</div>}
          </TabPane>
        )}
      </Tabs>
      
    </Modal>
  )
})
