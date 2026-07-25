/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Modal, Form, Input, DatePicker, Row, Col, message} from 'antd';
import {http} from 'libs';
import store from './departmentDutyLogStore';
import moment from 'moment';

@observer
class DepartmentDutyLogForm extends React.Component {
  formRef = React.createRef();
  state = {submitting: false};
  _mounted = false;

  componentDidMount() {
    this._mounted = true;
    const record = store.formRecord;
    if (record && record.id) {
      // 编辑模式
      this.formRef.current.setFieldsValue({
        duty_date: moment(record.duty_date),
        mains_voltage: record.mains_voltage,
        ups_voltage: record.ups_voltage,
        weather: record.weather,
        duty_record: record.duty_record,
        remark: record.remark,
        version: record.version,
      });
    }
    // 进入表单时预拉取当月已有值班日志日期，用于 DatePicker 面板标记
    this._loadDutyDatesForMoment(moment(record && record.duty_date ? record.duty_date : undefined));
  }

  componentWillUnmount() {
    this._mounted = false;
  }

  /**
   * 根据一个 moment 拉取其所属月份的已有值班日志日期到 store 缓存。
   * m 为空时使用今天。
   */
  _loadDutyDatesForMoment(m) {
    const target = m ? moment(m) : moment();
    store.fetchDutyDatesByMonth(target.year(), target.month() + 1);
  }

  handlePanelChange = (value) => {
    if (!value) return;
    this._loadDutyDatesForMoment(value);
  };

  renderDutyDateCell = (current) => {
    if (!current) return null;
    const dateStr = current.format('YYYY-MM-DD');
    const hasLog = store.hasDutyDate(dateStr);
    // 命中"已有值班日志"的日期填充浅绿底纹，其余保持原样（仅显示日期数字）
    if (!hasLog) return <div className="duty-date-cell">{current.date()}</div>;
    return <div className="duty-date-has-log">{current.date()}</div>;
  };

  handleSubmit = () => {
    this.formRef.current.validateFields().then(values => {
      this.setState({submitting: true});
      const payload = {
        duty_date: values.duty_date.format('YYYY-MM-DD'),
        mains_voltage: values.mains_voltage || '',
        ups_voltage: values.ups_voltage || '',
        weather: values.weather || '',
        duty_record: values.duty_record,
        remark: values.remark || '',
      };

      const record = store.formRecord;
      let request;
      if (record && record.id) {
        payload.version = record.version;
        request = http.put(`/api/department-duty-log/records/${record.id}/`, payload);
      } else {
        request = http.post('/api/department-duty-log/records/', payload);
      }

      request
        .then(() => {
          if (!this._mounted) return;
          message.success(record && record.id ? '编辑成功' : '新建成功');
          store.formVisible = false;
          store.fetchRecords();
        })
        .catch(err => {
          if (!this._mounted) return;
          if (err && err.includes('版本')) {
            message.error(err);
            // 版本冲突时不关闭表单，保留用户输入
          }
        })
        .finally(() => {
          if (this._mounted) this.setState({submitting: false});
        });
    });
  };

  render() {
    const record = store.formRecord;
    const isEdit = record && record.id;
    const currentUser = store.currentUser || {};

    return (
      <Modal
        title={isEdit ? '编辑值班日志' : '新建值班日志'}
        visible={store.formVisible}
        onCancel={() => store.formVisible = false}
        onOk={this.handleSubmit}
        confirmLoading={this.state.submitting}
        width={640}
        destroyOnClose
        maskClosable={false}
      >
        <style>{`
          .duty-date-cell {
            display: inline-block;
          }
          .duty-date-has-log {
            display: inline-block;
            min-width: 24px;
            height: 24px;
            line-height: 24px;
            border-radius: 2px;
            background-color: #d9f7be;
          }
          /* 选中态交给 antd 蓝色块，避免色块叠加 */
          .ant-picker-cell-selected .duty-date-has-log {
            background-color: transparent;
          }
        `}</style>
        <Form ref={this.formRef} layout="vertical">
          <Form.Item
            label="值班日期"
            name="duty_date"
            rules={[{required: true, message: '请选择值班日期'}]}
            extra="浅绿色底纹的日期表示当天已有值班日志记录"
          >
            <DatePicker
              style={{width: '100%'}}
              disabledDate={(current) => current && current > moment().endOf('day')}
              placeholder="选择值班日期"
              onPanelChange={this.handlePanelChange}
              dateRender={this.renderDutyDateCell}
            />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="值班员">
                <Input value={currentUser.name || ''} disabled/>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="市电电压"
                name="mains_voltage"
                rules={[
                  {required: true, message: '请输入市电电压'},
                  {max: 50, message: '最长50字符'},
                ]}
              >
                <Input placeholder="如：220V" maxLength={50}/>
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="UPS电压"
                name="ups_voltage"
                rules={[
                  {required: true, message: '请输入UPS电压'},
                  {max: 50, message: '最长50字符'},
                ]}
              >
                <Input placeholder="如：正常" maxLength={50}/>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="天气情况"
                name="weather"
                rules={[
                  {required: true, message: '请输入天气情况'},
                  {max: 50, message: '最长50字符'},
                ]}
              >
                <Input placeholder="如：晴" maxLength={50}/>
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            label="值班记录"
            name="duty_record"
            rules={[
              {required: true, message: '请输入值班记录'},
              {max: 10000, message: '最长10000字符'},
            ]}
          >
            <Input.TextArea
              rows={6}
              showCount
              maxLength={10000}
              placeholder="请输入当班情况"
            />
          </Form.Item>

          <Form.Item
            label="备注"
            name="remark"
            rules={[{max: 2000, message: '最长2000字符'}]}
          >
            <Input.TextArea rows={3} maxLength={2000} placeholder="补充说明（可选）"/>
          </Form.Item>
        </Form>
      </Modal>
    );
  }
}

export default DepartmentDutyLogForm;
