/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Breadcrumb } from 'antd';
import styles from './index.module.less';


export default class extends React.Component {
  static Item = Breadcrumb.Item

  render() {
    return (
      <div className={styles.breadcrumb}>
        <Breadcrumb>
          {this.props.children}
        </Breadcrumb>
        {this.props.extra ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
            {this.props.extra}
          </div>
        ) : null}
      </div>
    )
  }
}