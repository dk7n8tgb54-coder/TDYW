/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useRef, useState } from 'react';
import { observer } from 'mobx-react';
import { Layout, Button, Space, message } from 'antd';
import { ArrowLeftOutlined, SaveOutlined } from '@ant-design/icons';
import { Breadcrumb } from 'components';
import history from 'libs/history';
import { hasPermission } from 'libs/functools';
import store from './store';
import WorkbenchForm from './WorkbenchForm';
import styles from './Workbench.module.less';

const { Header, Content } = Layout;

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
      // 新建模式：获取下一个升级单号
      store.fetchNextUpgradeNo();
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
        message.error('加载数据失败');
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
    return (
      <Layout className={styles.layout}>
        <Header className={styles.header}>
          <div className={styles.headerLeft}>
            <Button icon={<ArrowLeftOutlined />} onClick={handleBack}>返回列表</Button>
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

  const canEdit = hasPermission('upgrade.upgrade.edit');

  return (
    <Layout className={styles.layout}>
      <Header className={styles.header}>
        <div className={styles.headerLeft}>
          <Button icon={<ArrowLeftOutlined />} onClick={handleBack}>返回列表</Button>
        </div>
        <div className={styles.headerTitle}>
          {isNew ? '新建升级申请' : `升级工作台 - ${store.record.upgrade_no || ''}`}
        </div>
        <div className={styles.headerRight}>
          <Space>
            {isNew ? (
              hasPermission('upgrade.upgrade.add') && (
                <>
                  <Button onClick={() => formRef.current && formRef.current.submit('list')} loading={loading}>
                    保存
                  </Button>
                  <Button type="primary" icon={<SaveOutlined />}
                    onClick={() => formRef.current && formRef.current.submit('workbench')} loading={loading}>
                    保存并进入工作台
                  </Button>
                </>
              )
            ) : (
              canEdit && (
                <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={loading}>
                  保存
                </Button>
              )
            )}
          </Space>
        </div>
      </Header>
      <Content className={styles.content}>
        <div className={styles.breadcrumb}>
          <Breadcrumb>
            <Breadcrumb.Item>首页</Breadcrumb.Item>
            <Breadcrumb.Item>系统升级管理</Breadcrumb.Item>
            <Breadcrumb.Item>
              <Button type="link" style={{padding: 0}} onClick={() => history.push('/upgrade')}>升级表单</Button>
            </Breadcrumb.Item>
            <Breadcrumb.Item>{isNew ? '新建' : store.record.upgrade_no}</Breadcrumb.Item>
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
