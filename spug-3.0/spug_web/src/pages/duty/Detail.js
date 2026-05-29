/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Descriptions, Card, Empty } from 'antd';
import store from './store';

export default observer(function () {
  const [detail, setDetail] = React.useState({});

  React.useEffect(() => {
    if (store.record.id) {
      setDetail(store.record);
    }
  }, []);

  return (
    <Modal
      visible={store.detailVisible}
      title="值班日志详情"
      onCancel={() => store.detailVisible = false}
      width={700}
      footer={null}
    >
      <Descriptions bordered column={2} style={{marginBottom: 16}}>
        <Descriptions.Item label="值班人员">{detail.duty_person}</Descriptions.Item>
        <Descriptions.Item label="填报人">{detail.reporter}</Descriptions.Item>
        <Descriptions.Item label="所属科室">{detail.department}</Descriptions.Item>
        <Descriptions.Item label="值班日期">{detail.duty_date}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{detail.created_at}</Descriptions.Item>
      </Descriptions>

      <Card title="值班情况">
        {detail.duty_situation
          ? <div style={{whiteSpace: 'pre-wrap', wordBreak: 'break-word'}}>{detail.duty_situation}</div>
          : <Empty description="暂无值班情况"/>}
      </Card>
    </Modal>
  );
})
