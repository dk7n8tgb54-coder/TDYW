/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Card, Empty } from 'antd';
import { Breadcrumb } from 'components';

export default function DataAnalysisIndex() {
  return (
    <div>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>数据分析</Breadcrumb.Item>
      </Breadcrumb>
      <Card>
        <Empty description="功能开发中" />
      </Card>
    </div>
  );
}
