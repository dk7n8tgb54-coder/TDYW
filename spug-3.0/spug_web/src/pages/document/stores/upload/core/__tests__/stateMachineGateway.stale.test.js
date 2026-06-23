/**
 * 7.1 状态机唯一入口 - 场景 8 旧异步回调不覆盖终态
 * 验证终态任务收到旧回调时 transition 返回 false，状态不被覆盖。
 */
import { setupGatewayEnv, teardownGatewayEnv } from './_gatewayEnv';

describe('7.1 场景8 旧异步回调不覆盖终态', () => {
  let env;
  beforeEach(() => { env = setupGatewayEnv(); });
  afterEach(() => { teardownGatewayEnv(env.adapter, env.manager); });

  it('8a 已 completed 的任务，旧 UPLOAD_COMPLETE/ERROR 回调 transition 返回 false', () => {
    const { manager, itemRef } = env;
    itemRef.totalChunks = 1;
    const machine = manager.create('stale-callback-completed', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });
    machine.transition('UPLOAD_COMPLETE');
    expect(machine.getState()).toBe('completed');

    expect(machine.transition('UPLOAD_COMPLETE')).toBe(false);
    expect(machine.transition('ERROR', { error: '晚到的错误' })).toBe(false);
    expect(machine.getState()).toBe('completed');
  });

  it('8b 已 cancelled 的任务，旧回调无法改回 uploading/completed', () => {
    const { manager, itemRef } = env;
    itemRef.totalChunks = 1;
    const machine = manager.create('stale-callback-cancelled', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('MD5_COMPLETE', { fileHash: 'abc123' });
    machine.transition('CANCEL');
    expect(machine.getState()).toBe('cancelled');

    expect(machine.transition('UPLOAD_COMPLETE')).toBe(false);
    expect(machine.transition('ERROR', { error: '晚到的错误' })).toBe(false);
    expect(machine.transition('PAUSE')).toBe(false);
    expect(machine.getState()).toBe('cancelled');
  });

  it('8c 已 error 的任务，旧 UPLOAD_COMPLETE 回调无法改成 completed', () => {
    const { manager, itemRef } = env;
    itemRef.totalChunks = 1;
    const machine = manager.create('stale-callback-error', { queueStore: env.mockQueueStore });
    machine.transition('START');
    machine.transition('ERROR', { error: '先到的失败' });
    expect(machine.getState()).toBe('error');

    expect(machine.transition('UPLOAD_COMPLETE')).toBe(false);
    expect(machine.getState()).toBe('error');
  });
});
