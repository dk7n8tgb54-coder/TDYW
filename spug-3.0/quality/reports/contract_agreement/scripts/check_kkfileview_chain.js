/**
 * kkFileView Office 预览链路巡检（环境级冒烟检查，针对真实运行栈）。
 *
 * 流程：登录 → 建合同 → 上传 docx → 取 preview-url → 解码回源 file_url
 *      → 同源请求回调验证字节 → 输出 KKFILEVIEW_PERSPECTIVE_URL 供
 *      从 kkfileview 容器内做回源连通性验证 → 清理测试数据。
 *
 * 用法（在 quality/e2e 目录下）：
 *   NODE_PATH=./node_modules node ../reports/contract_agreement/scripts/check_kkfileview_chain.js
 * 退出码 0=链路通过；非 0=失败（原因打印在输出中）。
 */
const fs = require('fs');
const path = require('path');

try {
  require('dotenv').config({ path: path.join(__dirname, '..', '..', '..', 'e2e', '.env') });
} catch (e) { /* 依赖真实环境变量时忽略 */ }

const { loginAndCreateContext, apiPost, apiGet } = require(
  path.join(__dirname, '..', '..', '..', 'e2e', 'helpers', 'api'));
const { request } = require('@playwright/test');

const LIST_API = '/api/contract-agreement/';
const DOCX_FIXTURE = path.join(__dirname, '..', '..', '..', 'e2e', 'test-data', 'e2e_minimal.docx');
const NAME = `E2E_CA_chain_check_${Date.now()}`;

(async () => {
  const docx = fs.readFileSync(DOCX_FIXTURE);
  const s = await loginAndCreateContext('admin');
  const { context: ctx } = s;
  let contractId = null;
  try {
    // 1. 建合同
    const created = await apiPost(ctx, LIST_API, {
      contract_name: NAME, contract_type: 'device_purchase',
      valid_start_date: '2026-01-01', valid_end_date: '2027-01-01',
      signing_party: '链路巡检签约方', responsible_user_id: s.data.id,
      responsible_user_name: 'admin', has_fee: false,
    });
    if (created.error) throw new Error(`建合同失败: ${created.error}`);
    contractId = created.data.id;

    // 2. 上传 docx（uploadCtx 不带默认 JSON Content-Type，避免污染 multipart 请求）
    const upCtx = await request.newContext({
      baseURL: process.env.E2E_BASE_URL || 'http://localhost:8080',
      extraHTTPHeaders: { 'X-Token': s.token },
    });
    const up = await upCtx.post(`${LIST_API}${contractId}/attachments/`, {
      multipart: {
        file: {
          name: 'chain_check.docx',
          mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          buffer: docx,
        },
      },
    });
    const upBody = await up.json();
    await upCtx.dispose();
    if (upBody.error) throw new Error(`上传失败: ${upBody.error}`);
    const attId = upBody.data.id;
    console.log(`[1] 合同 ${contractId} 附件 ${attId} 上传成功（${docx.length} 字节）`);

    // 3. preview-url
    const pv = await apiGet(ctx, `${LIST_API}attachments/${attId}/preview-url/`);
    if (pv.error) throw new Error(`preview-url 失败: ${pv.error}`);
    const previewUrl = pv.data.preview_url;
    console.log(`[2] preview_url: ${previewUrl}`);
    if (!previewUrl.includes('/kkfileview/onlinePreview?url=')) {
      throw new Error(`preview_url 未指向 kkFileView onlinePreview: ${previewUrl}`);
    }

    // 4. 解码回源 file_url
    const encoded = new URLSearchParams(new URL(previewUrl, 'http://localhost').search).get('url');
    const fileUrl = Buffer.from(encoded, 'base64').toString('utf-8');
    console.log(`[3] 回源 file_url: ${fileUrl}`);

    // 5. 同源请求回调，验证真实服务器按令牌返回一致字节
    const cbPath = fileUrl.slice(fileUrl.indexOf('/api/'));
    const cb = await ctx.get(cbPath);
    const body = await cb.body();
    if (cb.status() !== 200 || !body.equals(docx)) {
      throw new Error(`回调异常: status=${cb.status()} bytes=${body.length}/${docx.length}`);
    }
    console.log(`[4] 同源回调验证通过（200，${body.length} 字节一致）`);

    // 输出供 kkfileview 容器内回源连通性验证使用
    console.log(`KKFILEVIEW_PERSPECTIVE_URL=${fileUrl}`);
    console.log('CHAIN_OK');
  } finally {
    // KEEP_DATA=1 时保留数据，供外部从 kkfileview 容器内做回源连通性验证后再清理
    if (contractId && process.env.KEEP_DATA !== '1') {
      try { await ctx.delete(`${LIST_API}?id=${contractId}`); } catch (e) { /* 清理失败不掩盖结果 */ }
    }
    await ctx.dispose();
  }
})().catch(e => { console.error('CHAIN_FAIL:', e.message); process.exit(1); });
