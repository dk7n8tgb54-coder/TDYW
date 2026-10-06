/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useRef, useState } from 'react';
import { observer } from 'mobx-react';
import { Layout, Button, Space } from 'antd';
import { ArrowLeftOutlined, SaveOutlined } from '@ant-design/icons';
import { Breadcrumb } from 'components';
import history from 'libs/history';
import { hasPermission } from 'libs/functools';
import store from './store';
import WorkbenchForm from './WorkbenchForm';
import styles from './Workbench.module.less';

const { Header, Content } = Layout;

/** 记录加载完成前的占位视图 */
function WorkbenchLoading({onBack}) {
  return (
    <Layout className={styles.layout}>
      <Header className={styles.header}>
        <div className={styles.headerLeft}>
          <Button icon={<ArrowLeftOutlined />} onClick={onBack}>返回列表</Button>
        </div>
        <div className={styles.headerTitle}>加载中...</div>
        <div className={styles.headerRight} />
      </Header>
      <Content className={styles.content}>
        <div style={{ textAlign: 'center', padding: 50 }}>正在加载...</div>
      </Content>
    </Layout>
  );
}

/** 工作台顶栏：返回/标题/保存动作（新建走 add 权限，编辑走 edit 权限） */
function WorkbenchHeaderBar({isNew, loading, onBack, onSaveList, onSaveWorkbench, onSaveEdit}) {
  return (
    <Header className={styles.header}>
      <div className={styles.headerLeft}>
        <Button icon={<ArrowLeftOutlined />} onClick={onBack}>返回列表</Button>
      </div>
      <div className={styles.headerTitle}>
        {isNew ? '新建升级申请' : `升级工作台 - ${store.record.title || ''}`}
      </div>
      <div className={styles.headerRight}>
        <Space>
          {isNew ? (
            hasPermission('upgrade.upgrade.add') && (
              <>
                <Button onClick={onSaveList} loading={loading}>保存</Button>
                <Button type="primary" icon={<SaveOutlined />}
                  onClick={onSaveWorkbench} loading={loading}>
                  保存并进入工作台
                </Button>
              </>
            )
          ) : (
            hasPermission('upgrade.upgrade.edit') && (
              <Button type="primary" icon={<SaveOutlined />} onClick={onSaveEdit} loading={loading}>
                保存
              </Button>
            )
          )}
        </Space>
      </div>
    </Header>
  );
}

export default observer(function Workbench(props) {
  const recordId = props.match?.params?.id;
  const isNew = !recordId;
  
  const [loading, setLoading] = useState(false);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    // 清理之前的状态
    store.record = {};
    store.formVisible = false;
    
    if (isNew) {
      // 新建模式
      store.fetchPlans();
      store.fetchFilterOptions();
      store.fetchSystems();
      setInitialized(true);
    } else {
      // 查看/编辑模式：加载记录详情
      Promise.all([
        store.fetchRecord(recordId),
        store.fetchRecordSteps(recordId),
        store.fetchStatusLogs(recordId),
        store.fetchActionOptions(recordId),
        store.fetchFilterOptions(),
        store.fetchPlans(),
        store.fetchSystems(),
        store.fetchAttachmentCount(recordId),
      ]).then(() => {
        setInitialized(true);
      }).catch(() => {
        // 失败提示已由 http 拦截器弹出；记录加载失败只能退回列表
        history.push('/upgrade');
      });
    }

    return () => {
      // 清理
      store.record = {};
      store.recordSteps = [];
      store.recordStepStats = {};
      store.statusLogs = [];
      store.actionOptions = [];
    };
    // isNew 由 recordId 派生，仅依赖 recordId 等价且避免重复执行
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId]);

  const formRef = useRef(null);
  const handleSave = () => {
    if (formRef.current) {
      formRef.current.submit();
    }
  };

  const handleBack = () => {
    history.push('/upgrade');
  };

  if (!initialized) {
    return <WorkbenchLoading onBack={handleBack}/>;
  }

  return (
    <Layout className={styles.layout}>
      <WorkbenchHeaderBar
        isNew={isNew} loading={loading} onBack={handleBack}
        onSaveList={() => formRef.current && formRef.current.submit('list')}
        onSaveWorkbench={() => formRef.current && formRef.current.submit('workbench')}
        onSaveEdit={handleSave}/>
      <Content className={styles.content}>
        <div className={styles.breadcrumb}>
          <Breadcrumb>
            <Breadcrumb.Item>首页</Breadcrumb.Item>
            <Breadcrumb.Item>系统升级管理</Breadcrumb.Item>
            <Breadcrumb.Item>
              <Button type="link" style={{padding: 0}} onClick={() => history.push('/upgrade')}>升级表单</Button>
            </Breadcrumb.Item>
            <Breadcrumb.Item>{isNew ? '新建' : (store.record.title || '')}</Breadcrumb.Item>
          </Breadcrumb>
        </div>
        <WorkbenchForm
          ref={formRef}
          isNew={isNew}
          recordId={recordId}
          onSaveStart={() => setLoading(true)}
          onSaveEnd={() => setLoading(false)}
          onSaveSuccess={(recordId, redirectMode) => {
            if (isNew) {
              if (redirectMode === 'workbench' && recordId) {
                history.push(`/upgrade/workbench/${recordId}`);
              } else {
                history.push('/upgrade');
              }
            } else {
              history.push('/upgrade');
            }
          }}
          onSaveError={() => setLoading(false)}
        />
      </Content>
    </Layout>
  );
});
