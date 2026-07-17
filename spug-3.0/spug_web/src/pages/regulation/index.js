/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, Select } from 'antd';
import { AuthDiv, Breadcrumb, SearchForm } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import CategoryTree from './CategoryTree';
import CategoryForm from './CategoryForm';
import store from './store';
import styles from './index.module.less';

function RegulationIndex() {
  return (
    <AuthDiv auth="document.regulation.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>资料库</Breadcrumb.Item>
        <Breadcrumb.Item>规章管理</Breadcrumb.Item>
      </Breadcrumb>

      <div className={styles.container}>
        {/* 左侧分类树 */}
        <div className={styles.sidebar}>
          <CategoryTree />
        </div>

        {/* 右侧搜索 + 表格 */}
        <div className={styles.mainArea}>
          <SearchForm>
            <SearchForm.Item span={6} title="法规名称">
              <Input
                allowClear
                value={store.f_keyword}
                onChange={e => store.f_keyword = e.target.value}
                placeholder="规章名称或规章编号"
                onPressEnter={() => { store.pageNum = 1; store.fetchRecords(); }}
              />
            </SearchForm.Item>
            <SearchForm.Item span={6} title="业务类型">
              <Input
                allowClear
                value={store.f_biz_type}
                onChange={e => store.f_biz_type = e.target.value}
                placeholder="请输入业务类型"
                onPressEnter={() => { store.pageNum = 1; store.fetchRecords(); }}
              />
            </SearchForm.Item>
            <SearchForm.Item span={6} title="发文单位">
              <Input
                allowClear
                value={store.f_issuing_authority}
                onChange={e => store.f_issuing_authority = e.target.value}
                placeholder="请输入发文单位"
                onPressEnter={() => { store.pageNum = 1; store.fetchRecords(); }}
              />
            </SearchForm.Item>
            <SearchForm.Item span={6} title="状态">
              <Select
                allowClear
                value={store.f_status}
                onChange={v => { store.f_status = v; store.pageNum = 1; store.fetchRecords(); }}
                placeholder="请选择状态"
              >
                {store.statusOptions.map(item => (
                  <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
                ))}
              </Select>
            </SearchForm.Item>
          </SearchForm>

          <ComTable />
        </div>
      </div>

      {store.formVisible && <ComForm />}
      {store.detailVisible && <ComForm />}
      {store.categoryFormVisible && <CategoryForm />}
    </AuthDiv>
  );
}

export default observer(RegulationIndex);
