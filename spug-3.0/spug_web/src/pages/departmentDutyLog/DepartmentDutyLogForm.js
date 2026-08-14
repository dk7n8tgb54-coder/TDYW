/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Modal, Form, Input, DatePicker, Row, Col, message, Spin} from 'antd';
import {http} from 'libs';
import store from './departmentDutyLogStore';
import moment from 'moment';

@observer
class DepartmentDutyLogForm extends React.Component {
  formRef = React.createRef();
  state = {submitting: false};
  _mounted = false;
  _formFilled = false;
  _editId = null;    // 编辑时固定的记录 ID，防止异步覆盖
  _editVersion = null; // 编辑时固定的版本号

  componentDidMount() {
    this._mounted = true;
    this._tryFillForm();
  }

  componentDidUpdate() {
    this._tryFillForm();
  }

  componentWillUnmount() {
    this._mounted = false;
  }

  _tryFillForm() {
    // 新建模式直接返回
    if (!store.formLoading && !store.formRecord.id && !this._formFilled) {
      this._formFilled = true;
      this._loadDutyDatesForMoment(moment());
      return;
    }
    // 编辑模式：等详情加载完再填表单
    if (!store.formLoading && store.formRecord && store.formRecord.id && !this._formFilled) {
      this._formFilled = true;
      const record = store.formRecord;
      // 固定 id 和 version，防止异步响应覆盖 store.formRecord 后提交到错误记录
      this._editId = record.id;
      this._editVersion = record.version;
      this.formRef.current.setFieldsValue({
        duty_date: moment(record.duty_date),
        weather: record.weather,
        duty_record: record.duty_record,
        remark: record.remark,
      });
      this._loadDutyDatesForMoment(moment(record.duty_date));
    }
  }

  /**
   * 根据一个 moment 拉取其所属月份的已有已签署值班日志日期到 store 缓存。
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
    // 命中"已有已签署值班日志"的日期填充浅绿底纹，其余保持原样（仅显示日期数字）
    if (!hasLog) return <div className="duty-date-cell">{current.date()}</div>;
    return <div className="duty-date-has-log">{current.date()}</div>;
  };

  handleSubmit = () => {
    this.formRef.current.validateFields().then(values => {
      this.setState({submitting: true});
      const payload = {
        duty_date: values.duty_date.format('YYYY-MM-DD'),
        weather: values.weather || '',
        duty_record: values.duty_record,
        remark: values.remark || '',
      };

      let request;
      if (this._editId) {
        payload.version = this._editVersion;
        request = http.put(`/api/department-duty-log/records/${this._editId}/`, payload);
      } else {
        request = http.post('/api/department-duty-log/records/', payload);
      }

      request
        .then(() => {
          if (!this._mounted) return;
          message.success(this._editId ? '编辑成功' : '新建成功');
          store.formVisible = false;
          // 失效受影响月份的日期缓存
          const dutyMonth = payload.duty_date.slice(0, 7);
          const oldMonth = this._editId && store.formRecord.duty_date
            ? String(store.formRecord.duty_date).slice(0, 7) : null;
          const months = oldMonth && oldMonth !== dutyMonth
            ? [dutyMonth, oldMonth] : [dutyMonth];
          store.invalidateDutyDatesCache(months);
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

  handleCancel = () => {
    store.formVisible = false;
  };

  render() {
    const isEdit = !!(this._editId || (store.formRecord && store.formRecord.id));
    const currentUser = store.currentUser || {};

    return (
      <Modal
        title={isEdit ? '编辑值班日志' : '新建值班日志'}
        visible={store.formVisible}
        onCancel={this.handleCancel}
        onOk={this.handleSubmit}
        confirmLoading={this.state.submitting}
        okButtonProps={{disabled: store.formLoading}}
        width={640}
        destroyOnClose
        maskClosable={false}
      >
        {store.formLoading ? (
          <div style={{textAlign: 'center', padding: 40}}>
            <Spin tip="加载中..."/>
          </div>
        ) : (
        <>
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
            extra="浅绿色底纹的日期表示当天已有已签署的值班日志记录"
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
              <Form.Item label="值班人员">
                <Input value={currentUser.name || ''} disabled/>
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
            label="上级工作要求"
            name="remark"
            rules={[{max: 2000, message: '最长2000字符'}]}
          >
            <Input.TextArea rows={3} maxLength={2000} placeholder="补充说明（可选）"/>
          </Form.Item>
        </Form>
        </>
        )}
      </Modal>
    );
  }
}

export default DepartmentDutyLogForm;
