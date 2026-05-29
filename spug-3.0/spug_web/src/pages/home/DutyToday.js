/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { Card, List } from 'antd';
import { http } from 'libs';

function DutyToday(props) {
  const [fetching, setFetching] = useState(true);
  const [dutyRecords, setDutyRecords] = useState([]);

  useEffect(() => {
    fetchDutyRecords();
  }, []);

  function fetchDutyRecords() {
    setFetching(true);
    http.get('/api/home/duty/today/')
      .then(res => {
        const data = res?.records || (Array.isArray(res) ? res : []);
        setDutyRecords(data);
      })
      .finally(() => setFetching(false));
  }

  // 按账号分组，同一账号的排班合并显示
  const groupedRecords = dutyRecords.reduce((acc, item) => {
    const key = item.staff_id;
    if (!acc[key]) {
      acc[key] = {
        staff_id: item.staff_id,
        staff_name: item.staff_name,
        shifts: []
      };
    }
    acc[key].shifts.push(item.shift_name);
    return acc;
  }, {});

  const displayRecords = Object.values(groupedRecords);

  return (
    <Card
      title="今日值班"
      loading={fetching}
      className={props.className}>
      {displayRecords.length === 0 ? (
        <div style={{marginTop: 12, color: '#999'}}>暂无值班安排</div>
      ) : (
        <List
          dataSource={displayRecords}
          renderItem={item => (
            <List.Item key={item.staff_id}>
              <List.Item.Meta
                title={
                  <div style={{display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '8px'}}>
                    <span style={{fontWeight: 500}}>{item.staff_name}</span>
                    {item.shifts.map((shift, index) => (
                      <span key={index} style={{color: '#1890ff', background: '#e6f7ff', padding: '2px 8px', borderRadius: 4, fontSize: 12}}>
                        {shift}
                      </span>
                    ))}
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}

export default DutyToday;
