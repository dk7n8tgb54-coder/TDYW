/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 巡检单记录页——导出日期范围选择弹窗（仅供列表页三个导出按钮复用，
 * 详情抽屉单条导出不经过本弹窗）。
 * 受控组件：日期值、可导出条数与导出状态由父级持有，弹窗内修改不回写
 * 列表筛选条件；确认时校验日期完整性，校验失败提示且不触发导出。
 * 条数仅作提示：统计失败或为空不阻断确认，最终由后端导出接口统一校验。
 */
import React from 'react';
import {DatePicker, Modal, message} from 'antd';

class DutyRangeExportModal extends React.Component {
  // RangePicker onChange 的统一入口（jsdom 测试亦经此路径设置日期）
  handleRangeChange = (range) => {
    const {onChange} = this.props;
    if (typeof onChange === 'function') onChange(range || []);
  };

  handleOk = () => {
    const {value, exporting, onConfirm} = this.props;
    if (exporting) return;
    if (!value || value.length !== 2 || !value[0] || !value[1]) {
      message.warning('请选择起始日期和截止日期');
      return;
    }
    // 按自然日字符串比较，避免时刻/时区差异导致日期前后误判
    if (value[0].format('YYYY-MM-DD') > value[1].format('YYYY-MM-DD')) {
      message.warning('起始日期不能晚于截止日期');
      return;
    }
    if (typeof onConfirm === 'function') onConfirm(value);
  };

  renderCount() {
    const {count, countLoading} = this.props;
    if (countLoading) {
      return <span style={{color: '#999'}}>正在统计所选日期范围内可导出的条数…</span>;
    }
    if (typeof count !== 'number') return null;
    if (count === 0) {
      return (
        <span style={{color: '#f5222d'}}>
          当前筛选条件下，所选日期范围内没有可导出的数据
        </span>
      );
    }
    return <span>当前筛选条件下，所选日期范围内共可导出 {count} 条巡检单记录</span>;
  }

  render() {
    const {visible, value, exporting, onCancel} = this.props;
    return (
      <Modal
        title="选择导出日期范围"
        visible={visible}
        confirmLoading={!!exporting}
        okText="确认"
        cancelText="取消"
        maskClosable={false}
        onCancel={onCancel}
        onOk={this.handleOk}>
        <DatePicker.RangePicker
          value={value}
          onChange={this.handleRangeChange}
          format="YYYY-MM-DD"
          placeholder={['值班日起', '值班日止']}
          style={{width: '100%'}}
        />
        <div style={{marginTop: 8, minHeight: 22, fontSize: 13}}>
          {this.renderCount()}
        </div>
      </Modal>
    );
  }
}

export default DutyRangeExportModal;
