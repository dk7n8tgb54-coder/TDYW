/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, DatePicker, Button, message, Checkbox, Spin, Tabs, Empty, Tag } from 'antd';
import { ImportOutlined } from '@ant-design/icons';
import { http } from 'libs';
import moment from 'moment';
import store from './store';

const { TabPane } = Tabs;

// 各模块配置
const SOURCE_CONFIG = {
  runlog: { label: '跨日事项跟踪', color: '#1890ff', tag: '跨日事项跟踪' },
  interference: { label: '干扰记录', color: '#fa8c16', tag: '干扰记录' },
};

// 渲染单条记录的通用卡片
function RecordCard({ item, checked, onToggle }) {
  const config = SOURCE_CONFIG[item.source] || {};
  return (
    <div style={{
      padding: 12,
      marginBottom: 8,
      border: '1px solid #e8e8e8',
      borderRadius: 4,
      backgroundColor: checked ? '#e6f7ff' : '#fff',
      cursor: 'pointer',
    }} onClick={() => onToggle(item.id)}>
      <Checkbox value={item.id} checked={checked} style={{marginRight: 8}}>
        <strong>{item.title}</strong>
      </Checkbox>
      <Tag color={config.color} style={{marginLeft: 8, fontSize: 12}}>{config.tag}</Tag>
      {item.sub_title && <span style={{marginLeft: 8, color: '#999', fontSize: 12}}>{item.sub_title}</span>}
      {(item.sequence !== undefined && item.sequence !== null) && (
        <span style={{marginLeft: 8, color: '#999', fontSize: 12}}>序号{item.sequence}</span>
      )}
      {item.recorder && (
        <span style={{marginLeft: 8, color: '#999', fontSize: 12}}>{item.recorder}</span>
      )}
      <div style={{
        marginTop: 4,
        marginLeft: 24,
        color: '#555',
        whiteSpace: 'pre-wrap',
        maxHeight: 80,
        overflow: 'auto',
        fontSize: 13,
      }}>
        {item.content}
      </div>
    </div>
  );
}

export default observer(function () {
  const [form] = Form.useForm();
  const [importVisible, setImportVisible] = React.useState(false);
  const [importLoading, setImportLoading] = React.useState(false);
  const [importData, setImportData] = React.useState({ runlog: [], interference: [], upgrade: [] });
  const [importSelected, setImportSelected] = React.useState([]);
  const [activeTab, setActiveTab] = React.useState('runlog');

  React.useEffect(() => {
    if (store.record.id) {
      const data = {...store.record};
      if (data.duty_date) {
        data.duty_date = moment(data.duty_date);
      }
      if (data.report_time) {
        data.report_time = moment(data.report_time);
      }
      form.setFieldsValue(data);
    } else {
      form.setFieldsValue({
        reporter: sessionStorage.getItem('nickname') || '',
        report_time: moment(),
      });
    }
  }, [form]);

  const handleSubmit = () => {
    form.validateFields().then(values => {
      if (values.duty_date) {
        values.duty_date = values.duty_date.format('YYYY-MM-DD');
      }

      if (store.record.id) {
        http.post('/api/duty/duty/', {id: store.record.id, ...values})
          .then(() => {
            message.success('更新成功');
            store.fetchRecords();
            store.formVisible = false;
          });
      } else {
        http.post('/api/duty/duty/', values)
          .then(() => {
            message.success('创建成功');
            store.fetchRecords();
            store.formVisible = false;
          });
      }
    });
  };

  // 打开引入弹窗
  function openImportModal() {
    setImportSelected([]);
    setImportVisible(true);
    setImportLoading(true);

    const dutyDate = form.getFieldValue('duty_date');
    const targetDate = dutyDate ? dutyDate.format('YYYY-MM-DD') : moment().format('YYYY-MM-DD');

    http.get('/api/duty/duty/import_records/', {params: {date: targetDate}})
      .then(res => {
        setImportData({
          runlog: res.runlog || [],
          interference: res.interference || [],
          upgrade: res.upgrade || [],
        });
      })
      .catch(() => {
        message.error('获取当日记录失败');
      })
      .finally(() => setImportLoading(false));
  }

  // 切换选中
  function toggleSelect(id) {
    setImportSelected(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  }

  // 确认引入
  function handleImportConfirm() {
    if (importSelected.length === 0) {
      message.warning('请至少选择一条记录');
      return;
    }

    // 从所有分类中找到选中项
    const allItems = [...importData.runlog, ...importData.interference, ...importData.upgrade];
    const selectedItems = allItems.filter(u => importSelected.includes(u.id));

    // 按模块分组拼接
    const grouped = {};
    selectedItems.forEach(item => {
      const source = item.source;
      if (!grouped[source]) grouped[source] = [];
      grouped[source].push(item);
    });

    const config = SOURCE_CONFIG;
    const parts = [];
    Object.keys(grouped).forEach(source => {
      const header = `--- 引入${config[source]?.label || source} ---`;
      const content = grouped[source].map(item => {
        let line = `【${item.title}`;
        if (item.sequence !== undefined && item.sequence !== null) line += ` - 序号${item.sequence}`;
        if (item.recorder) line += ` - ${item.recorder}`;
        line += `】\n${item.content}`;
        return line;
      }).join('\n\n');
      parts.push(header + '\n' + content);
    });

    const importText = parts.join('\n\n');
    const currentContent = form.getFieldValue('duty_situation') || '';
    const newContent = currentContent ? currentContent + '\n\n' + importText : importText;
    form.setFieldsValue({ duty_situation: newContent });

    message.success(`已引入 ${importSelected.length} 条记录`);
    setImportVisible(false);
    setImportSelected([]);
  }

  // 计算各Tab数量
  const tabCounts = {
    runlog: importData.runlog.length,
    interference: importData.interference.length,
    upgrade: importData.upgrade.length,
  };
  const totalCount = tabCounts.runlog + tabCounts.interference + tabCounts.upgrade;

  // 渲染某个Tab下的记录列表
  function renderTabList(items) {
    if (items.length === 0) {
      return <Empty description="当日暂无记录" style={{padding: 24}} />;
    }
    return items.map(item => (
      <RecordCard
        key={item.id}
        item={item}
        checked={importSelected.includes(item.id)}
        onToggle={toggleSelect}
      />
    ));
  }

  return (
    <Modal
      visible={store.formVisible}
      title={store.record.id ? '编辑值班日志' : '新建值班日志'}
      onCancel={() => store.formVisible = false}
      width={700}
      footer={[
        <Button key="cancel" onClick={() => store.formVisible = false}>取消</Button>,
        <Button key="submit" type="primary" onClick={handleSubmit}>保存</Button>
      ]}
    >
      <Form form={form} labelCol={{span: 5}} wrapperCol={{span: 17}}>
        <Form.Item name="duty_person" label="值班人员" rules={[{required: true, message: '请输入值班人员'}]}>
          <Input placeholder="请输入值班人员"/>
        </Form.Item>
        <Form.Item name="reporter" label="填报人">
          <Input disabled placeholder="自动填入登录账号姓名"/>
        </Form.Item>
        <Form.Item name="department" label="所属科室" rules={[{required: true, message: '请输入所属科室'}]}>
          <Input placeholder="请输入所属科室"/>
        </Form.Item>
        <Form.Item name="duty_date" label="值班日期" rules={[{required: true, message: '请选择值班日期'}]}>
          <DatePicker style={{width: '100%'}}/>
        </Form.Item>
        <Form.Item name="report_time" label="上报时间">
          <DatePicker showTime disabled style={{width: '100%'}}/>
        </Form.Item>
        <Form.Item name="duty_situation" label="值班情况">
          <Input.TextArea rows={6} placeholder="请输入值班情况"/>
        </Form.Item>
        <Form.Item wrapperCol={{offset: 5, span: 17}}>
          <Button size="small" icon={<ImportOutlined/>} onClick={openImportModal}>
            引入当日记录
          </Button>
          <span style={{marginLeft: 8, color: '#999', fontSize: 12}}>
            跨日事项跟踪 / 干扰记录
          </span>
        </Form.Item>
      </Form>

      {/* 引入记录弹窗 */}
      <Modal
        title="引入当日记录"
        visible={importVisible}
        width={750}
        onCancel={() => { setImportVisible(false); setImportSelected([]); }}
        footer={[
          <span key="hint" style={{marginRight: 16, color: '#999'}}>
            已选 {importSelected.length} 条 / 共 {totalCount} 条
          </span>,
          <Button key="cancel" onClick={() => { setImportVisible(false); setImportSelected([]); }}>取消</Button>,
          <Button key="confirm" type="primary" onClick={handleImportConfirm} disabled={importSelected.length === 0}>
            确认引入 ({importSelected.length})
          </Button>,
        ]}
      >
        <Spin spinning={importLoading}>
          {totalCount === 0 && !importLoading ? (
            <Empty description="当日暂无任何可引入的记录" style={{padding: 40}}/>
          ) : (
            <Tabs activeKey={activeTab} onChange={setActiveTab} size="small">
              <TabPane tab={`跨日事项跟踪 (${tabCounts.runlog})`} key="runlog">
                {renderTabList(importData.runlog)}
              </TabPane>
              <TabPane tab={`干扰记录 (${tabCounts.interference})`} key="interference">
                {renderTabList(importData.interference)}
              </TabPane>
            </Tabs>
          )}
        </Spin>
      </Modal>
    </Modal>
  );
})
