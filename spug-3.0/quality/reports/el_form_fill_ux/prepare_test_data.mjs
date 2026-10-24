/**
 * 填写体验验收轮（2026-10-24）专用测试数据准备脚本。
 *
 * 仅面向本机开发环境（E2E_BASE_URL，缺省 http://localhost:8080）：
 * 1. 以 E2E 管理员账号登录取 token；
 * 2. 创建专用数字表单模板（名称带 E2E_ 前缀，便于识别与清理）；
 * 3. 写入长表单草稿（覆盖三种结构、宽/窄矩阵、v2 属性键）并发布；
 * 4. 输出模板 id / 版本 id 供浏览器验收与填写流程使用。
 *
 * 不访问生产、不修改既有数据；重复运行会新建同构模板（旧的可人工删除）。
 */
import {readFileSync} from 'node:fs';
import {join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ENV = {};
try {
  for (const line of readFileSync(join(HERE, '..', '..', 'e2e', '.env'), 'utf8').split(/\r?\n/)) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (m) ENV[m[1]] = m[2];
  }
} catch (e) {
  console.error('读取 quality/e2e/.env 失败：', e.message);
  process.exit(1);
}
const BASE = process.env.E2E_BASE_URL || ENV.E2E_BASE_URL || 'http://localhost:8080';
const USERNAME = process.env.E2E_ADMIN_USERNAME || ENV.E2E_ADMIN_USERNAME || 'admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD || ENV.E2E_ADMIN_PASSWORD;

async function api(method, path, body, token) {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? {'x-token': token} : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (json.error) throw new Error(`${method} ${path} -> ${json.error}`);
  return json.data ?? json;
}

let seq = 0;
const id = prefix => `${prefix}${String(++seq).padStart(4, '0')}`;

/** 长表单：7 组覆盖三种结构 + 宽/窄矩阵 + v2 属性键（约 45 字段）。 */
function buildLongForm() {
  const groups = [];
  // 一、基本信息（fields）：覆盖全部六种字段类型与 v2 属性键
  groups.push({
    id: id('g'), name: '基本信息', kind: 'fields', description: '设备与登记信息',
    fields: [
      {id: id('f'), name: '设备名称', type: 'text', required: true},
      {id: id('f'), name: '设备编号', type: 'text', required: true},
      {id: id('f'), name: '安装位置', type: 'text'},
      {id: id('f'), name: '本次维护日期', type: 'date', required: true},
      {id: id('f'), name: '维护级别', type: 'choice', required: true,
        options: ['一级保养', '二级保养', '专项检修']},
      {id: id('f'), name: '供电电压', type: 'number', unit: 'V', min: 0, max: 500},
      {id: id('f'), name: '绝缘电阻', type: 'number', unit: 'MΩ', min: 0, precision: 2},
      {id: id('f'), name: '维护结论', type: 'normal_abnormal', required: true,
        require_desc_when_abnormal: true},
      {id: id('f'), name: '备注说明', type: 'textarea', rows: 4},
    ],
  });
  // 二、逐项状态检查（fields）：12 个判定项，撑长画布
  groups.push({
    id: id('g'), name: '逐项状态检查', kind: 'fields',
    fields: Array.from({length: 12}, (_, i) => ({
      id: id('f'), name: `检查项目${i + 1}：状态判定`, type: 'normal_abnormal',
      required: i < 4, require_desc_when_abnormal: i < 4,
      description: i === 0 ? '目视检查外观有无锈蚀、变形' : '',
    })),
  });
  // 三、测量记录（repeat）：可增删行
  groups.push({
    id: id('g'), name: '测量记录', kind: 'repeat', item_name: '测量条目',
    fields: [
      {id: id('f'), name: '测量点位', type: 'text', required: true},
      {id: id('f'), name: '测量值', type: 'number', unit: 'mm', min: 0, precision: 2, required: true},
      {id: id('f'), name: '测量时间', type: 'date'},
      {id: id('f'), name: '仪器编号', type: 'text'},
    ],
  });
  // 四、少列矩阵（3 行 × 2 列）：验证少列时单元格控件宽度封顶
  groups.push({
    id: id('g'), name: '双机对比检查', kind: 'matrix',
    columns: [
      {id: id('c'), name: '1号机'}, {id: id('c'), name: '2号机'},
    ],
    fields: [
      {id: id('r'), name: '外观状态', type: 'normal_abnormal', require_desc_when_abnormal: true},
      {id: id('r'), name: '指示灯状态', type: 'normal_abnormal'},
      {id: id('r'), name: '运行温度', type: 'number', unit: '℃', min: 0, max: 200},
    ],
  });
  // 五、运行参数（fields）：10 个短值数字项
  groups.push({
    id: id('g'), name: '运行参数记录', kind: 'fields',
    fields: Array.from({length: 10}, (_, i) => ({
      id: id('f'), name: `参数通道${i + 1}读数`, type: 'number', unit: 'dB',
      min: -100, max: 20, precision: 1,
    })),
  });
  // 六、宽矩阵（6 行 × 8 列）：验证横向溢出与列宽
  groups.push({
    id: id('g'), name: '多机运行对比', kind: 'matrix',
    columns: Array.from({length: 8}, (_, i) => ({id: id('c'), name: `${i + 1}号设备`})),
    fields: [
      {id: id('r'), name: '外观检查', type: 'normal_abnormal', require_desc_when_abnormal: true},
      {id: id('r'), name: '供电状态', type: 'normal_abnormal'},
      {id: id('r'), name: '输出功率', type: 'number', unit: 'kW', min: 0, precision: 1},
      {id: id('r'), name: '驻波比', type: 'number', min: 1, max: 10, precision: 2},
      {id: id('r'), name: '工作模式', type: 'choice', options: ['主用', '备用', '离线']},
      {id: id('r'), name: '告警代码', type: 'text'},
    ],
  });
  // 七、综合备注（textarea 行数上限验证）
  groups.push({
    id: id('g'), name: '综合备注', kind: 'fields',
    fields: [
      {id: id('f'), name: '遗留问题与处理情况', type: 'textarea', rows: 6},
      {id: id('f'), name: '下次维护建议', type: 'textarea', rows: 2},
    ],
  });
  return {protocol_version: 2, groups};
}

const login = await api('POST', '/api/account/login/', {username: USERNAME, password: PASSWORD});
const token = login.access_token || (login.data && login.data.access_token) || login.token;
if (!token) throw new Error('登录响应中未找到 token：' + JSON.stringify(Object.keys(login)));

const stamp = new Date().toISOString().slice(5, 16).replace(/[-:T]/g, '');
const template = await api('POST', '/api/equipment-lifecycle/form-templates/', {
  name: `E2E_填写体验_长表单_${stamp}`,
  ledger_type: 'week_month',
  description: '填写体验验收专用测试模板（自动化创建，可随时删除）',
}, token);

const form = buildLongForm();
await api('PUT', `/api/equipment-lifecycle/form-templates/${template.id}/`, {form}, token);
const published = await api('POST',
  `/api/equipment-lifecycle/form-templates/${template.id}/publish/`, {}, token);

console.log(JSON.stringify({
  base: BASE,
  template_id: template.id,
  template_name: template.name,
  version_id: published.version && published.version.id || published.id,
  version_no: published.version && published.version.version_no,
  groups: form.groups.length,
}, null, 2));
