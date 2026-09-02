/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect, useRef } from 'react';
import { Table, Space, Divider, Popover, Checkbox, Button, Input, Select } from 'antd';
import { ReloadOutlined, SettingOutlined, FullscreenOutlined, SearchOutlined } from '@ant-design/icons';
import styles from './index.module.less';
import {useResizableColumns} from './resizableColumns';
import tableFieldsStore from './tableFieldsStore';

function Search(props) {
  let keys = props.keys || [''];
  keys = keys.map(x => x.split('/'));
  const [key, setKey] = useState(keys[0][0]);
  return (
    <Input
      allowClear
      style={{width: '280px'}}
      placeholder="输入检索"
      prefix={<SearchOutlined style={{color: '#c0c0c0'}}/>}
      onChange={e => props.onChange(key, e.target.value)}
      addonBefore={(
        <Select value={key} onChange={setKey}>
          {keys.map(item => (
            <Select.Option key={item[0]} value={item[0]}>{item[1]}</Select.Option>
          ))}
        </Select>
      )}/>
  )
}

function Footer(props) {
  const actions = props.actions || [];
  const length = props.selected.length;
  return length > 0 ? (
    <div className={styles.tableFooter}>
      <div className={styles.left}>已选择 <span>{length}</span> 项</div>
      <Space size="middle">
        {actions.map((item, index) => (
          <React.Fragment key={index}>{item}</React.Fragment>
        ))}
      </Space>
    </div>
  ) : null
}

function Header(props) {
  const columns = props.columns || [];
  const actions = props.actions || [];
  const fields = props.fields || [];
  const onFieldsChange = props.onFieldsChange;
  const selectableColumns = columns.filter(item => !item.fixed);

  const Fields = () => {
    return (
      <Checkbox.Group value={fields} onChange={onFieldsChange}>
        {columns.map((item, index) => item.fixed ? null : (
          <Checkbox value={index} key={index}>{item.title}</Checkbox>
        ))}
      </Checkbox.Group>
    )
  }

  function handleCheckAll(e) {
    if (e.target.checked) {
      onFieldsChange(selectableColumns.map(item => columns.indexOf(item)))
    } else {
      onFieldsChange([])
    }
  }

  function handleFullscreen() {
    if (props.rootRef.current && document.fullscreenEnabled) {
      if (document.fullscreenElement) {
        document.exitFullscreen()
      } else {
        props.rootRef.current.requestFullscreen()
      }
    }
  }

  return (
    <div className={styles.toolbar}>
      <div className={styles.title}>{props.title}</div>
      <div className={styles.option}>
        <Space size="middle" style={{marginRight: 10}}>
          {actions.map((item, index) => (
            <React.Fragment key={index}>{item}</React.Fragment>
          ))}
        </Space>
        {actions.length ? <Divider type="vertical"/> : null}
        <Space className={styles.icons}>
          <ReloadOutlined onClick={props.onReload}/>
          <Popover
            arrowPointAtCenter
            destroyTooltipOnHide={{keepParent: false}}
            title={[
              <Checkbox
                key="1"
                checked={fields.filter(index => !columns[index].fixed).length === selectableColumns.length}
                indeterminate={![0, selectableColumns.length].includes(fields.filter(index => !columns[index].fixed).length)}
                onChange={handleCheckAll}>列展示</Checkbox>,
              <Button
                key="2"
                type="link"
                style={{padding: 0}}
                onClick={() => onFieldsChange(props.defaultFields)}>重置</Button>,
              ...(props.resizable ? [
                <Button
                  key="3"
                  type="link"
                  style={{padding: 0, marginLeft: 8}}
                  onClick={props.onWidthsReset}>重置列宽</Button>
              ] : [])
            ]}
            overlayClassName={styles.tableFields}
            trigger="click"
            placement="bottomRight"
            content={<Fields/>}>
            <SettingOutlined/>
          </Popover>
          <FullscreenOutlined onClick={handleFullscreen}/>
        </Space>
      </div>
    </div>
  )
}

function TableCard(props) {
  const rootRef = useRef();
  const batchActions = props.batchActions || [];
  const selected = props.selected || [];
  const resizable = !!props.resizable;
  const [fields, setFields] = useState([]);
  const [defaultFields, setDefaultFields] = useState([]);
  const [columns, setColumns] = useState([]);
  const {resizableColumns, components: resizableComponents, resetAllWidths} =
    useResizableColumns(props.tKey, columns, {enabled: resizable});

  useEffect(() => {
    let mounted = true;
    let _columns = props.columns || [];
    if (props.children) {
      if (Array.isArray(props.children)) {
        _columns = props.children.filter(x => x.props).map(x => x.props)
      } else {
        _columns = [props.children.props]
      }
    }
    let hideFields = _columns.filter(x => x.hide).map(x => x.title)
    const applyFields = persistedFields => {
      if (!mounted) return;
      const selected = persistedFields || hideFields;
      const fields = _columns.reduce((result, item, index) => {
        if (!selected.includes(item.title)) result.push(index);
        return result;
      }, []);
      setFields(fields);
      setColumns(_columns);
      setDefaultFields(_columns.reduce((result, item, index) => {
        if (!hideFields.includes(item.title)) result.push(index);
        return result;
      }, []));
    };
    setColumns(_columns);
    applyFields(hideFields);
    if (props.tKey) {
      tableFieldsStore.load().then(() => {
        applyFields(tableFieldsStore.get(props.tKey));
      });
    }
    return () => { mounted = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleFieldsChange(fields) {
    setFields(fields)
    if (props.tKey) {
      const tableFields = {...tableFieldsStore.fields};
      tableFields[props.tKey] = columns.filter((_, index) => !fields.includes(index)).map(x => x.title);
      tableFieldsStore.fields = tableFields;
      tableFieldsStore.save();
    }
  }

  const baseColumns = resizable ? resizableColumns : columns;
  const visibleColumns = baseColumns.filter((column, index) => column.fixed || fields.includes(index));
  let tableScroll = props.scroll;
  if (resizable && visibleColumns.length && visibleColumns.every(col => typeof col.width === 'number')) {
    const extra = (props.rowSelection ? 60 : 0) + (props.expandable ? 48 : 0);
    tableScroll = {x: visibleColumns.reduce((sum, col) => sum + col.width, 0) + extra};
  }

  return (
    <div ref={rootRef} className={styles.tableCard}>
      <Header
        title={props.title}
        columns={columns}
        actions={props.actions}
        fields={fields}
        rootRef={rootRef}
        defaultFields={defaultFields}
        resizable={resizable}
        onWidthsReset={resetAllWidths}
        onFieldsChange={handleFieldsChange}
        onReload={props.onReload}/>
      <Table
        tableLayout={resizable ? 'fixed' : props.tableLayout}
        scroll={tableScroll}
        components={resizableComponents}
        rowKey={props.rowKey}
        loading={props.loading}
        columns={visibleColumns}
        dataSource={props.dataSource}
        rowSelection={props.rowSelection}
        expandable={props.expandable}
        pagination={props.pagination}
        onRow={props.onRow}/>
      {selected.length ? <Footer selected={selected} actions={batchActions}/> : null}
    </div>
  )
}

TableCard.Search = Search;
export default TableCard
