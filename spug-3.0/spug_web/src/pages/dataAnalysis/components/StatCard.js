/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Card, Statistic, Skeleton } from 'antd';

export default function StatCard({ title, value, suffix, loading, prefix }) {
  return (
    <Card size="small" bodyStyle={{ padding: '16px 20px' }}>
      {loading ? (
        <Skeleton active paragraph={{ rows: 1 }} title={{ width: '60%' }} />
      ) : (
        <Statistic
          title={title}
          value={value}
          suffix={suffix}
          prefix={prefix}
        />
      )}
    </Card>
  );
}
