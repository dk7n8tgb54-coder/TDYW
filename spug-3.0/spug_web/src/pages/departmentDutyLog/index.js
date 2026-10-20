/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Input, Select, DatePicker, Button} from 'antd';
import {AuthDiv, SearchForm} from 'components';
import ComTable from './DepartmentDutyLogTable';
import ComForm from './DepartmentDutyLogForm';
import ComDetail from './DepartmentDutyLogDetail';
import ComSignModal from './DepartmentDutyLogSignModal';
import ComExportButton from './DepartmentDutyLogExportButton';
import {PlusOutlined} from '@ant-design/icons';
import store from './departmentDutyLogStore';

const {RangePicker} = DatePicker;

/**
 * 筛选区（2026-10-20 统一交互，参照运行处置记录 RecordFilters）：
 * 常驻 关键字（草稿，查询/回车提交）/日期范围/状态，值班人员收入
 * "更多筛选"；下拉与日期变更即查询但不代提交文本草稿；重置清空全部
 * 条件及草稿并回到第 1 页；展开收起本身不触发请求，收起时显示折叠区
 * 已启用条件数量。
 */
function DepartmentDutyLogIndex() {
  const [advancedOpen, setAdvancedOpen] = React.useState(false);
  const advancedCount = [store.input_duty_person_name].filter(Boolean).length;
  return (
    <AuthDiv auth="department_duty_log.department_duty_log.view">
      <SearchForm>
        <SearchForm.Item span={6} title="关键字">
          <Input
            allowClear
            value={store.input_keyword}
            onChange={e => store.setKeywordInput(e.target.value)}
            placeholder="值班记录/上级工作要求"
            onPressEnter={() => store.commitFilters()}
          />
        </SearchForm.Item>
        <SearchForm.Item span={8} title="日期范围">
          <RangePicker
            allowClear
            value={[store.f_start_date, store.f_end_date]}
            onChange={(dates) => {
              store.f_start_date = dates ? dates[0] : undefined;
              store.f_end_date = dates ? dates[1] : undefined;
              store.pageNum = 1;
              store.fetchRecords();
            }}
            style={{width: '100%'}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={4} title="状态">
          <Select
            allowClear
            value={store.f_status}
            onChange={v => {store.f_status = v; store.pageNum = 1; store.fetchRecords();}}
            placeholder="选择状态"
          >
            {store.statusOptions.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Actions
          onSearch={() => store.commitFilters()}
          onReset={() => {store.resetFilter(); store.fetchRecords();}}
          advancedOpen={advancedOpen}
          advancedCount={advancedCount}
          onToggleAdvanced={() => setAdvancedOpen(!advancedOpen)}
        />
        {advancedOpen && (
          <SearchForm.Item span={6} title="值班人员">
            <Input
              allowClear
              value={store.input_duty_person_name}
              onChange={e => store.setDutyPersonNameInput(e.target.value)}
              placeholder="值班人员姓名"
              onPressEnter={() => store.commitFilters()}
            />
          </SearchForm.Item>
        )}
      </SearchForm>

      <div style={{marginBottom: 16}}>
        <AuthDiv auth="department_duty_log.department_duty_log.add" style={{display: 'inline-block'}}>
          <Button type="primary" icon={<PlusOutlined/>}
            onClick={() => store.showForm(null)}
          >新建值班日志</Button>
        </AuthDiv>
        <span style={{marginLeft: 8}}>
          <ComExportButton/>
        </span>
      </div>

      <ComTable/>

      {store.formVisible && <ComForm/>}
      {store.detailVisible && <ComDetail/>}
      {store.signVisible && <ComSignModal/>}
    </AuthDiv>
  );
}

export default observer(DepartmentDutyLogIndex);
