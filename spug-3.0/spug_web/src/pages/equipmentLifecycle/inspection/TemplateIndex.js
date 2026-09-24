/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——巡检模板管理（今日巡检改造）。
 * 模板结构 = 巡检模板 → 设备名称 → 检查内容（设备名称不关联系统）；
 * 录入类型两种：正常/不正常单选（choice）与数字/文本（text）；
 * 停用/修改模板不影响历史巡检记录（明细保存全量快照）。
 */
import React, {useEffect} from 'react';
import {observer} from 'mobx-react';
import {Button, Tag, Input, Popconfirm, message} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {AuthButton, AuthDiv, Breadcrumb, SearchForm} from 'components';
import store from './store';
import TemplateForm from './TemplateForm';
import {PERM_ITPL} from './constants';

@observer
class TemplateIndex extends React.Component {
  componentDidMount() {
    store.fetchTplList();
  }

  render() {
    return (
      <AuthDiv>
        <Breadcrumb>
          <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
          <Breadcrumb.Item>运行维护</Breadcrumb.Item>
          <Breadcrumb.Item>巡检模板</Breadcrumb.Item>
        </Breadcrumb>
        <SearchForm>
          <SearchForm.Item>
            <Input
              allowClear
              placeholder="模板名称"
              onChange={e => {
                store.f_keyword = e.target.value;
              }}
              onKeyPress={e => {
                if (e.key === 'Enter') {
                  store.page = 1;
                  store.fetchTplList({keyword: store.f_keyword});
                }
              }}
            />
          </SearchForm.Item>
        </SearchForm>
        <div style={{marginBottom: 12}}>
          <AuthButton
            auth={PERM_ITPL.ADD}
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => {
              store.tplRecord = null;
              store.tplFormVisible = true;
            }}
          >
            新增模板
          </AuthButton>
        </div>
        <table className="el-ins-recap-table" style={{width: '100%'}}>
          <thead>
          <tr>
            <th>模板名称</th>
            <th>说明</th>
            <th>设备名称数</th>
            <th>状态</th>
            <th>创建时间</th>
            <th style={{width: 200}}>操作</th>
          </tr>
          </thead>
          <tbody>
          {store.templateRecords.map(t => (
            <tr key={t.id}>
              <td>{t.name}</td>
              <td>{t.description || '-'}</td>
              <td>{t.devices_count}</td>
              <td>
                {t.is_active
                  ? <Tag color="green">启用</Tag>
                  : <Tag color="default">停用</Tag>}
              </td>
              <td>{t.created_at}</td>
              <td>
                <AuthButton
                  auth={PERM_ITPL.EDIT}
                  type="link"
                  size="small"
                  style={{padding: 0}}
                  onClick={() => {
                    store.fetchTplDetail(t.id).then(detail => {
                      store.tplRecord = detail;
                      store.tplFormVisible = true;
                    }).catch(() => {});
                  }}
                >
                  编辑
                </AuthButton>
                <Popconfirm
                  title={`确定${t.is_active ? '停用' : '启用'}模板「${t.name}」？`}
                  onConfirm={() => {
                    store.toggleTpl(t.id, !t.is_active)
                      .then(() => message.success('操作成功'))
                      .then(() => store.fetchTplList())
                      .catch(() => {});
                  }}
                >
                  <AuthButton auth={PERM_ITPL.EDIT} type="link" size="small"
                              style={{padding: 0, marginLeft: 8}}>
                    {t.is_active ? '停用' : '启用'}
                  </AuthButton>
                </Popconfirm>
                <Popconfirm
                  title="确定删除该模板？仅未被巡检单引用的模板可删除。"
                  onConfirm={() => {
                    store.deleteTpl(t.id)
                      .then(() => message.success('已删除'))
                      .then(() => store.fetchTplList())
                      .catch(() => {});
                  }}
                >
                  <AuthButton auth={PERM_ITPL.DEL} type="link" size="small"
                              style={{padding: 0, marginLeft: 8, color: 'red'}}>
                    删除
                  </AuthButton>
                </Popconfirm>
              </td>
            </tr>
          ))}
          </tbody>
        </table>
        {store.tplFormVisible && <TemplateForm/>}
      </AuthDiv>
    );
  }
}

export default TemplateIndex;
