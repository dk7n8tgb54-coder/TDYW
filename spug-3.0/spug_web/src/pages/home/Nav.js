/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { Avatar, Card, Col, Row } from 'antd';
import { http } from 'libs';
import styles from './index.module.less';

function NavIndex(props) {
  const [records, setRecords] = useState([]);

  useEffect(() => {
    fetchRecords()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function fetchRecords() {
    http.get('/api/home/navigation/')
      .then(res => setRecords(res))
  }

  return (
    <Card
      title="便捷导航"
      className={styles.nav}
      bodyStyle={{paddingBottom: 0, minHeight: 166}}>
      <Row gutter={24}>
        {records.map(item => (
          <Col key={item.id} span={6} style={{marginBottom: 24}}>
            <Card
              hoverable
              actions={item.links.map(x => <a href={x.url} rel="noopener noreferrer" target="_blank">{x.name}</a>)}>
              <Card.Meta
                avatar={<Avatar size="large" src={item.logo}/>}
                title={item.title}
                description={item.desc}/>
            </Card>
          </Col>
        ))}
      </Row>
    </Card>
  )
}

export default NavIndex