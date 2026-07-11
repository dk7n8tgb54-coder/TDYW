/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, Select, DatePicker } from 'antd';
import { SearchForm, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import store from './store';
import moment from 'moment';

function ContractAgreement() {
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get('id');
    if (id) {
      store.fetchDetail(id);
    }
  }, []);

  return (
    <AuthDiv auth="contract_agreement.agreement.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>合同协议</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="合同名称">
          <Input
            allowClear
            value={store.f_contract_name}
            onChange={e => store.f_contract_name = e.target.value}
            placeholder="请输入合同名称"
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="类型">
          <Select
            allowClear
            value={store.f_contract_type}
            onChange={v => store.f_contract_type = v}
            placeholder="请选择类型"
          >
            {store.contractTypeOptions.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="状态">
          <Select
            allowClear
            value={store.f_status}
            onChange={v => store.f_status = v}
            placeholder="请选择状态"
          >
            {store.statusOptions.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="费用">
          <Select
            allowClear
            value={store.f_has_fee}
            onChange={v => store.f_has_fee = v}
            placeholder="请选择费用"
          >
            <Select.Option value={true}>有</Select.Option>
            <Select.Option value={false}>无</Select.Option>
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="签约方">
          <Input
            allowClear
            value={store.f_signing_party}
            onChange={e => store.f_signing_party = e.target.value}
            placeholder="请输入签约方"
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="截止日期">
          <DatePicker.RangePicker
            allowClear
            value={store.f_valid_end_range
              ? [moment(store.f_valid_end_range[0]), moment(store.f_valid_end_range[1])]
              : null}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                store.f_valid_end_range = [
                  dates[0].format('YYYY-MM-DD'),
                  dates[1].format('YYYY-MM-DD')
                ];
              } else {
                store.f_valid_end_range = undefined;
              }
            }}
            placeholder={['开始日期', '结束日期']}
            style={{width: '100%'}}
          />
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      {store.formVisible && <ComForm/>}
      {store.detailVisible && <ComForm/>}
    </AuthDiv>
  );
}

export default observer(ContractAgreement);
