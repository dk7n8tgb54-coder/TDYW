/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Tabs, Select } from 'antd';
import TemplateTable from './TemplateTable';
import TemplateForm from './TemplateForm';
import CheckSheet from './CheckSheet';
import DataView from './DataView';
import store from './store';

const { Option } = Select;

export default observer(function CheckSheetIndex() {
  useEffect(() => {
    store.fetchTemplates();
  }, []);

  const handleProjectFilter = (value) => {
    store.f_project = value || '';
  };

  return (
    <div>
      <Tabs defaultActiveKey="template">
        <Tabs.TabPane tab="检查表模板管理" key="template">
          <div style={{ marginBottom: 16 }}>
            <Select
              placeholder="筛选项目名称"
              style={{ width: 300 }}
              allowClear
              onChange={handleProjectFilter}
            >
              {store.projects.map(proj => (
                <Option key={proj} value={proj}>{proj}</Option>
              ))}
            </Select>
          </div>
          <TemplateTable />
          <TemplateForm />
        </Tabs.TabPane>
        <Tabs.TabPane tab="日检查表录入" key="checksheet">
          <CheckSheet />
        </Tabs.TabPane>
        <Tabs.TabPane tab="数据查看与导出" key="dataView">
          <DataView />
        </Tabs.TabPane>
      </Tabs>
    </div>
  );
})
