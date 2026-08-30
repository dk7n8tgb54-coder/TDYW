/**
 * 新建 / 编辑协作任务
 * - 新建：基本信息 + 材料清单（动态行）+ 交付对象多选（各科室账号，一人一号，显示人名）
 * - 编辑：仅标题、说明、截止时间（材料清单与分派对象派活后不可变更）
 */
import React, {useState, useEffect, useRef} from 'react';
import {Modal, Form, Input, DatePicker, Select, Button, Space, notification} from 'antd';
import {PlusOutlined, MinusCircleOutlined} from '@ant-design/icons';
import moment from 'moment';
import {http} from 'libs';
import {buildTaskPayload} from './utils';

export default function TaskForm(props) {
  const {record, onCancel, onOk} = props;
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [accounts, setAccounts] = useState([]);
  const [selectedAccounts, setSelectedAccounts] = useState([]);
  const aliveRef = useRef(true); // 弹窗可能先于异步回调卸载，避免卸载后 setState
  const isEdit = !!(record && record.id);

  useEffect(() => () => { aliveRef.current = false; }, []);

  useEffect(() => {
    if (isEdit) return; // 编辑模式不加载交付对象（不可改）
    let cancelled = false;
    http.get('/api/coop-task/departments/')
      .then(list => { if (!cancelled) setAccounts(list || []); })
      .catch(() => { if (!cancelled) setAccounts([]); });
    return () => { cancelled = true; };
  }, [isEdit]);

  useEffect(() => {
    if (isEdit) {
      form.setFieldsValue({
        title: record.title,
        description: record.description,
        deadline: record.deadline ? moment(record.deadline, 'YYYY-MM-DD HH:mm') : undefined,
      });
    }
  }, [isEdit, record, form]);

  const handleSubmit = (values) => {
    setLoading(true);
    let request;
    if (isEdit) {
      request = http.post(`/api/coop-task/tasks/${record.id}/`, {
        title: values.title,
        description: values.description || '',
        deadline: values.deadline ? values.deadline.format('YYYY-MM-DD HH:mm:ss') : '',
      });
    } else {
      const payload = buildTaskPayload(values, selectedAccounts);
      request = http.post('/api/coop-task/tasks/', payload);
    }
    request.then((task) => {
      notification.success({message: isEdit ? '任务已更新' : '任务已创建并分派'});
      // 创建成功把新任务回传给列表页，用于自动打开详情引导上传模板
      onOk(isEdit ? undefined : task);
    })
      .catch(() => {
        // 错误已由 http 拦截器统一提示；弹窗仍在时才恢复按钮
        if (aliveRef.current) setLoading(false);
      });
  };

  return (
    <Modal
      title={isEdit ? '编辑任务' : '新建协作任务'}
      visible
      width={720}
      confirmLoading={loading}
      onCancel={onCancel}
      onOk={() => form.submit()}
    >
      <Form form={form} layout="vertical" onFinish={handleSubmit}>
        <Form.Item name="title" label="任务标题" rules={[{required: true, message: '请输入任务标题'}]}>
          <Input maxLength={200} placeholder="如：征集5月工作台账"/>
        </Form.Item>
        <Form.Item name="description" label="任务说明与要求">
          <Input.TextArea rows={3} maxLength={20000} placeholder="交付要求、模板位置等说明（可选）"/>
        </Form.Item>
        <Form.Item name="deadline" label="交付截止时间" rules={[{required: true, message: '请选择交付截止时间'}]}>
          <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
        </Form.Item>

        {!isEdit && (
          <>
            <Form.Item label="交付对象" required
                       extra="选择各科室的交付账号（一人一号，显示经办人姓名）；创建后材料清单与分派对象不可变更，如需调整请作废后重新发起。">
              <Select
                mode="multiple"
                showSearch
                optionFilterProp="children"
                value={selectedAccounts}
                placeholder="请选择需要配合交付材料的科室账号"
                onChange={v => setSelectedAccounts(v)}
                style={{width: '100%'}}>
                {accounts.map(a => (
                  <Select.Option key={a.id} value={a.id}>
                    {a.tenant_name ? `${a.name}（${a.tenant_name}）` : a.name}
                  </Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item label="材料清单" required>
              <Form.List name="items" initialValue={[{name: '', remark: ''}]}>
                {(fields, {add, remove}) => (
                  <>
                    {fields.map(field => (
                      <Space key={field.key} align="baseline" style={{display: 'flex', marginBottom: 4}}>
                        <Form.Item
                          name={[field.name, 'name']}
                          fieldKey={[field.fieldKey, 'name']}
                          rules={[{required: true, message: '请输入材料名称'}]}
                          noStyle>
                          <Input placeholder="材料名称，如：工作总结" style={{width: 260}} maxLength={200}/>
                        </Form.Item>
                        <Form.Item
                          name={[field.name, 'remark']}
                          fieldKey={[field.fieldKey, 'remark']}
                          noStyle>
                          <Input placeholder="格式等要求（可选）" style={{width: 260}} maxLength={500}/>
                        </Form.Item>
                        {fields.length > 1 && (
                          <MinusCircleOutlined onClick={() => remove(field.name)}/>
                        )}
                      </Space>
                    ))}
                    <Button type="dashed" onClick={() => add()} icon={<PlusOutlined/>}
                            style={{width: 200}}>
                      添加材料
                    </Button>
                  </>
                )}
              </Form.List>
            </Form.Item>
          </>
        )}
      </Form>
    </Modal>
  );
}
