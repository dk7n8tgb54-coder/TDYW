/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 周期台账一键新增弹窗（2026-10-11 最小实现）。
 *
 * - 用户选择维护类型（页面入口已定）与对应周期：周月维护按月（YYYY-MM）、
 *   季维护按航季分夏秋季/冬春季（YYYY-夏秋 / YYYY-冬春，YYYY 为航季开始
 *   年份），周月维护不拆分周维护/月维护；
 * - 范围展示 = 后端返回的本租户在用系统数（GET /ledgers/batch-create/），
 *   不编造台账；同周期已存在的台账由后端幂等跳过；
 * - 结果（实际新增/已存在）以后端返回为准，成功提示仅在真实成功后弹出；
 * - antd 4.21.5：Modal 用 visible，Form 用 Form.useForm()（支持外部受控 form 注入）。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Alert, DatePicker, Form, Modal, Select, message} from 'antd';
import moment from 'moment';
import {LEDGER_TYPE_TEXT, LEDGER_TYPE} from './constants';

const MONTH_FORMAT = 'YYYY-MM';

/** 航季选项：夏秋季 / 冬春季（与后端 YYYY-夏秋 / YYYY-冬春 周期串对齐）。 */
const SEASON_OPTIONS = [
  {value: '夏秋', label: '夏秋季'},
  {value: '冬春', label: '冬春季'},
];

function LedgerBatchCreateModal({visible, ledgerType, store, onCancel, form: externalForm}) {
  const [innerForm] = Form.useForm();
  const form = externalForm || innerForm;
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [optionsLoaded, setOptionsLoaded] = useState(false);
  const isSeasonal = ledgerType === LEDGER_TYPE.SEASONAL;

  useEffect(() => {
    if (visible) {
      form.resetFields();
      setResult(null);
      setOptionsLoaded(false);
      store.fetchSystemOptions().then(() => setOptionsLoaded(true));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const activeCount = store.systemOptions.filter(s => s.is_active).length;

  const handleOk = () => {
    form.validateFields().then(values => {
      // 周月维护取月份选择器值格式化为 YYYY-MM；季维护 = 航季年份-航季（如 2026-冬春）
      const period = isSeasonal
        ? `${values.season_year.format('YYYY')}-${values.season}`
        : values.period.format(MONTH_FORMAT);
      setSubmitting(true);
      store.batchCreate({ledger_type: ledgerType, period})
        .then(res => {
          // 只有后端确认成功后才提示成功；失败由 http 拦截器统一提示
          setResult(res || null);
          if (res) {
            message.success(
              `${res.period_text}实际新增 ${res.created} 张台账，已存在 ${res.existed} 张`);
          }
        })
        .catch(() => {})
        .finally(() => setSubmitting(false));
    }).catch(() => {});
  };

  return (
    <Modal
      title={`一键新增${LEDGER_TYPE_TEXT[ledgerType]}台账`}
      visible={visible}
      confirmLoading={submitting}
      onOk={handleOk}
      onCancel={onCancel}
      okText="新增"
      destroyOnClose>
      <Alert
        type="info"
        showIcon
        style={{marginBottom: 16}}
        message={
          optionsLoaded
            ? `将为本租户 ${activeCount} 个在用系统各创建 1 张草稿台账；同周期已存在的台账自动跳过。`
            : '正在获取在用系统…'
        }
        description="创建的台账为草稿（不含明细），实际执行日期暂记创建当日，请在台账详情中补录维护项目并修正执行日期。"/>
      {optionsLoaded && activeCount === 0 && (
        <Alert type="warning" showIcon style={{marginBottom: 16}} message="没有在用系统，无法批量新增台账"/>
      )}
      <Form form={form} layout="vertical">
      {isSeasonal ? (
        <React.Fragment>
          <Form.Item
            label="航季年份"
            name="season_year"
            rules={[{required: true, message: '请选择航季年份'}]}
            extra="航季以开始年份命名：夏秋季自当年3月末起，冬春季自当年10月末起（跨年）">
            <DatePicker style={{width: '100%'}} picker="year" placeholder="请选择年份"/>
          </Form.Item>
          <Form.Item
            label="航季"
            name="season"
            rules={[{required: true, message: '请选择夏秋季或冬春季'}]}>
            <Select placeholder="请选择航季" options={SEASON_OPTIONS}/>
          </Form.Item>
        </React.Fragment>
      ) : (
        <Form.Item
          label="维护周期"
          name="period"
          rules={[{required: true, message: '请选择月份'}]}
          extra="按月选择，例如 2026年10月">
          <DatePicker style={{width: '100%'}} picker="month" placeholder="请选择月份"/>
        </Form.Item>
      )}
      </Form>
      {result && (
        <Alert
          type="success"
          showIcon
          message={`实际新增 ${result.created} 张，已存在 ${result.existed} 张`}
          description={
            result.existed > 0
              ? `已存在的系统：${result.existed_systems.join('、')}`
              : undefined
          }/>
      )}
    </Modal>
  );
}

export default observer(LedgerBatchCreateModal);
