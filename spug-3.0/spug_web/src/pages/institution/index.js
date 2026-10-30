/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { AuthDiv, SearchForm, FilterBar } from 'components';
import store from './store';
import ComTable from './Table';
import ManualForm from './ManualForm';
import CategoryModal from './CategoryModal';

@observer
class InstitutionIndex extends React.Component {
  componentDidMount() {
    store.fetchRecords();
    store.fetchCategories();
  }

  render() {
    return (
      <AuthDiv auth="institution.manual.view">
        <FilterBar
          store={store}
          fields={[
            {key: 'f_keyword', label: '关键词', type: 'input', span: 6,
              props: {placeholder: '名称 / 编号 / 归属单位'}},
            {key: 'f_category_id', label: '类别', type: 'select', span: 6,
              options: () => (store.categories || [])
                .filter(c => c.is_active)
                .map(c => ({value: c.id, label: c.name}))},
            {key: 'f_owner_type', label: '归属类型', type: 'select', span: 5,
              options: [
                {value: 'department', label: '部门'},
                {value: 'section', label: '科室'},
              ]},
            {key: 'f_status', label: '状态', type: 'select', span: 5,
              options: [
                {value: 'active', label: '启用'},
                {value: 'archived', label: '归档'},
              ]},
          ]}
          onSearch={() => {
            store.pageNum = 1;
            store.fetchRecords();
          }}/>
        <ComTable/>
        {store.formVisible && <ManualForm/>}
        {store.categoryVisible && <CategoryModal/>}
      </AuthDiv>
    );
  }
}

export default InstitutionIndex;
