import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}
let container = null;
beforeEach(() => {container = document.createElement('div'); document.body.appendChild(container);});
afterEach(() => {ReactDOM.unmountComponentAtNode(container); document.body.removeChild(container);});
function flush() {return new Promise(resolve => setTimeout(resolve, 0));}
function btns() {return Array.from(document.querySelectorAll('button')).map(b => b.textContent.replace(/\s+/g, ''));}

const SYSTEMS = [{id: 1, system_code: 'S1', name: '系统A', install_location: '机房A'}];
const DETAIL = {id: 11, record_no: 'YX-1', system: 1, system_name: '系统A', system_code: 'S1',
  system_location: '机房A', occurred_at: '2026-10-01 08:30', title: '标题X',
  description: '描述', status: 'recorded', status_text: '已记录', needs_follow_up: false,
  affects_system_operation: true, impact_status: 'interrupted', importance: 'normal',
  converted_fault: 88, converted_fault_no: 'GZ-1', created_by_name: 'a', created_at: 'x',
  measures_taken: '', handling_result: '', importance_reason: '', importance_marked_at: null,
  importance_marked_by_name: '', updated_at: null};

describe('debug', () => {
  it('closed-state buttons', async () => {
    const store = require('../store').default;
    const RecordDetail = require('../RecordDetail').default;
    mockHttpGet.mockImplementation(() => Promise.resolve({data: [], total: 0}));
    await act(async () => {
      store.showDetail({...DETAIL, status: 'closed'});
      ReactDOM.render(<RecordDetail/>, container);
    });
    await act(async () => {await flush();});
    console.log('CLOSED BTNS:', JSON.stringify(btns()));
    console.log('STORE STATUS:', store.detail.status);
  });

  it('form ok buttons', async () => {
    const store = require('../store').default;
    const RecordForm = require('../RecordForm').default;
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/candidate-systems')) return Promise.resolve({data: SYSTEMS});
      return Promise.resolve({data: [], total: 0});
    });
    await act(async () => {
      store.showForm();
      ReactDOM.render(<RecordForm/>, container);
    });
    await act(async () => {await flush();});
    console.log('FORM BTNS:', JSON.stringify(btns()));
    console.log('MODAL COUNT:', document.querySelectorAll('.ant-modal').length);
    console.log('MODAL WRAP COUNT:', document.querySelectorAll('.ant-modal-wrap').length);
  });
});
