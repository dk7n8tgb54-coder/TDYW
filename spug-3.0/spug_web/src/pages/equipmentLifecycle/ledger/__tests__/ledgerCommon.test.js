/**
 * 台账录入公共逻辑测试：数字/文本行的填写值解析。
 *
 * 数字/文本为模板项目两种录入类型之一（另一为正常/不正常）：
 * 纯数字填写值同时产出 value_number 便于整洁存储；结果无自动判定，
 * 全部由填写人手动选择（数值上下限字段已移除）。
 */
import {parseFreeValue} from '../ledgerCommon';

describe('parseFreeValue 数字/文本填写值解析', () => {
  test('纯数字输入同时产出 value_number', () => {
    expect(parseFreeValue('25.6')).toEqual({value_text: '25.6', value_number: 25.6});
    expect(parseFreeValue(' 48 ')).toEqual({value_text: ' 48 ', value_number: 48});
    expect(parseFreeValue('-3')).toEqual({value_text: '-3', value_number: -3});
  });

  test('非数字输入仅保留文本', () => {
    expect(parseFreeValue('正常')).toEqual({value_text: '正常', value_number: null});
    expect(parseFreeValue('48.5V')).toEqual({value_text: '48.5V', value_number: null});
    expect(parseFreeValue('')).toEqual({value_text: '', value_number: null});
  });
});
