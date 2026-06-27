/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Row, Col, Form, Input, Select, Button, DatePicker } from 'antd';
import moment from 'moment';
import styles from './index.module.less';

// 默认栅格宽度
const DEFAULT_SPAN = 6;

/**
 * 解析 options，统一成 { value, label } 结构。
 * 支持字符串数组、{ label, value } 对象数组，以及函数形式（延迟求值）。
 * valueProp / labelProp 可覆盖对象数组读取的字段名。
 */
function resolveOptions(field) {
  const { options, valueProp = 'value', labelProp = 'label' } = field;
  const raw = typeof options === 'function' ? options() : (options || []);
  return raw.map(item => {
    if (item === null || item === undefined) return { value: '', label: '' };
    if (typeof item === 'object') {
      return { value: item[valueProp], label: item[labelProp] };
    }
    return { value: item, label: item };
  });
}

/**
 * 根据字段类型返回重置时的空值。
 */
function emptyValueFor(field) {
  if (field.type === 'multipleSelect' || field.type === 'dateRange') return [];
  return null;
}

/**
 * 公共筛选栏组件。
 * 基于 SearchForm 的视觉外壳，通过 store + fields 配置渲染常见筛选控件，
 * 并提供统一的查询 / 重置按钮。业务 store 继续负责 fetchRecords / resetFilter 等语义。
 */
function FilterBar(props) {
  const {
    store,
    fields = [],
    onSearch,
    onReset,
    beforeSearch,
    onValuesChange,
    showSearch = true,
    showReset = true,
    searchText = '查询',
    resetText = '重置',
    buttonSpan,
    style,
  } = props;

  // 复用现有页面 open={isMounted ? undefined : false} 的处理方式，
  // 在组件卸载阶段强制关闭下拉，避免遗留浮层。
  const [mounted, setMounted] = React.useState(true);
  React.useEffect(() => {
    return () => setMounted(false);
  }, []);

  function getValue(field) {
    const value = store[field.key];
    if (field.type === 'dateRange') {
      if (Array.isArray(value) && value.length === 2 && value[0] && value[1]) {
        return [moment(value[0]), moment(value[1])];
      }
      return null;
    }
    return value;
  }

  function setValue(field, value) {
    if (field.onChange) {
      field.onChange(value, { store, field });
    } else {
      store[field.key] = value;
    }
    if (onValuesChange) onValuesChange(field, value, store);
  }

  function handleSearch() {
    if (beforeSearch) beforeSearch();
    if (onSearch) onSearch();
  }

  function handleReset() {
    if (onReset) {
      onReset();
      return;
    }
    fields.forEach(field => {
      store[field.key] = emptyValueFor(field);
    });
  }

  function renderField(field) {
    const allowClear = field.allowClear !== false;
    const placeholder = field.placeholder;
    const extraProps = field.props || {};

    if (field.type === 'custom') {
      const value = getValue(field);
      const setValueFn = (v) => setValue(field, v);
      return field.render({ store, field, value, setValue: setValueFn });
    }

    if (field.type === 'input') {
      return (
        <Input
          allowClear={allowClear}
          value={getValue(field)}
          onChange={e => setValue(field, e.target.value)}
          placeholder={placeholder}
          {...extraProps}
        />
      );
    }

    if (field.type === 'select' || field.type === 'multipleSelect') {
      const isMultiple = field.type === 'multipleSelect';
      const mode = field.mode || (isMultiple ? 'multiple' : undefined);
      const options = resolveOptions(field);
      return (
        <Select
          allowClear={allowClear}
          mode={mode}
          value={getValue(field)}
          onChange={v => setValue(field, v)}
          placeholder={placeholder || '请选择'}
          open={mounted ? undefined : false}
          {...extraProps}
        >
          {options.map(opt => (
            <Select.Option key={opt.value} value={opt.value}>{opt.label}</Select.Option>
          ))}
        </Select>
      );
    }

    if (field.type === 'dateRange') {
      const format = field.format || 'YYYY-MM-DD';
      return (
        <DatePicker.RangePicker
          allowClear={allowClear}
          value={getValue(field)}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              setValue(field, [dates[0].format(format), dates[1].format(format)]);
            } else {
              setValue(field, []);
            }
          }}
          format={format}
          placeholder={placeholder || ['开始日期', '结束日期']}
          style={{ width: '100%' }}
          open={mounted ? undefined : false}
          {...extraProps}
        />
      );
    }

    return null;
  }

  // 按钮区域栅格：优先使用传入的 buttonSpan；否则自动占据当前行剩余宽度，
  // 字段刚好填满一行时按钮独占新行。
  const usedSpan = fields.reduce((sum, f) => sum + (f.span || DEFAULT_SPAN), 0);
  const remaining = 24 - (usedSpan % 24);
  const autoButtonSpan = remaining > 0 && remaining < 24 ? remaining : 24;
  const btnSpan = buttonSpan != null ? buttonSpan : autoButtonSpan;

  return (
    <div className={styles.searchForm} style={style}>
      <Form>
        <Row gutter={{ md: 8, lg: 24, xl: 48 }}>
          {fields.map(field => (
            <Col key={field.key} span={field.span || DEFAULT_SPAN}>
              <Form.Item label={field.label}>
                {renderField(field)}
              </Form.Item>
            </Col>
          ))}
          {(showSearch || showReset) && (
            <Col span={btnSpan}>
              <Form.Item>
                {showSearch && (
                  <Button type="primary" onClick={handleSearch}>{searchText}</Button>
                )}
                {showReset && (
                  <Button onClick={handleReset} style={{ marginLeft: 8 }}>{resetText}</Button>
                )}
              </Form.Item>
            </Col>
          )}
        </Row>
      </Form>
    </div>
  );
}

export default observer(FilterBar);
