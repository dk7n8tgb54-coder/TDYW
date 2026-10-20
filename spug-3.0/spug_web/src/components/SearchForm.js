/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Row, Col, Form, Button } from 'antd';
import { DownOutlined, UpOutlined } from '@ant-design/icons';
import styles from './index.module.less';

export default class SearchForm extends React.Component {
  static Item(props) {
    return (
      <Col span={props.span} offset={props.offset} style={props.style}>
        <Form.Item label={props.title}>
          {props.children}
        </Form.Item>
      </Col>
    )
  }

  /**
   * 筛选区操作行（2026-10-20 统一六模块筛选交互新增，参照运行处置记录
   * RecordFilters）：查询（提交文本草稿并回到第 1 页，由调用方实现）、
   * 重置（清空全部条件及草稿后刷新）、"更多筛选"折叠开关——收起时显示
   * 已启用条件数量（advancedCount 由调用方按"条件是否已设置"计算，
   * false 等有效布尔值须计入、日期范围按一个条件计数）。展开收起本身
   * 不触发请求。span 缺省 6，与常见 7/7/4 或 6/6/6 常驻布局合计 24。
   */
  static Actions(props) {
    return (
      <SearchForm.Item span={props.span || 6}>
        <Button type="primary" onClick={props.onSearch}>查询</Button>
        <Button style={{marginLeft: 8}} onClick={props.onReset}>重置</Button>
        <a
          style={{marginLeft: 16, lineHeight: '32px', userSelect: 'none'}}
          onClick={props.onToggleAdvanced}
        >
          {props.advancedOpen ? '收起筛选' : '更多筛选'}
          {!props.advancedOpen && props.advancedCount > 0 && `（${props.advancedCount}）`}
          {props.advancedOpen
            ? <UpOutlined style={{marginLeft: 4}}/>
            : <DownOutlined style={{marginLeft: 4}}/>}
        </a>
      </SearchForm.Item>
    );
  }

  render() {
    return (
      <div className={styles.searchForm} style={this.props.style}>
        <Form style={this.props.style}>
          <Row gutter={{md: 8, lg: 24, xl: 48}}>
            {this.props.children}
          </Row>
        </Form>
      </div>
    )
  }
}
