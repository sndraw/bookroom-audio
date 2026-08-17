/**
 * @bookroom/audio-sdk 新增功能单元测试
 *
 * 覆盖：
 * 1. 心跳保活（heartbeatInterval 定时发送 PING）
 * 2. PONG 回调（RTT 计算）
 * 3. pause() / resume() 发送消息与状态机
 * 4. 非法状态/模式下的 pause/resume 抛错
 * 5. 指数退避重连 + 重连后自动重发 START 恢复会话
 * 6. 主动 close() 不触发重连
 *
 * 运行方式（sdk/typescript 目录）：
 *   npm run build && npm test
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  BookRoomASRClient,
} from '../dist/index.mjs';

// ==================== Fake WebSocket ====================

class FakeWebSocket {
  static instances = [];
  readyState = 0;
  OPEN = 0;
  CLOSED = 3;
  sent = [];
  handlers = null;

  constructor(url, handlers) {
    this.url = url;
    this.handlers = handlers;
    FakeWebSocket.instances.push(this);
  }

  send(data) {
    this.sent.push(data);
  }

  close(code = 1000, reason = '') {
    this.readyState = this.CLOSED;
    this.closedWith = { code, reason };
  }

  // ---------- 测试辅助 ----------
  simulateOpen() {
    this.readyState = this.OPEN;
    this.handlers.onOpen?.();
  }

  simulateMessage(text) {
    // 客户端 handleMessage 仅接受字符串消息，对象自动序列化
    if (typeof text !== 'string') text = JSON.stringify(text);
    this.handlers.onMessage?.(text);
  }

  simulateClose(code, reason) {
    this.handlers.onClose?.(code, reason);
  }

  parsedSent() {
    return this.sent
      .filter((d) => typeof d === 'string')
      .map((d) => {
        try {
          return JSON.parse(d);
        } catch {
          return d;
        }
      });
  }

  sentOfType(type) {
    return this.parsedSent().filter((m) => m && m.type === type);
  }
}

/** 创建注入 FakeWebSocket 的工厂，返回 { factory, latest, count } */
function makeFactory() {
  FakeWebSocket.instances = [];
  const factory = (url, handlers) => new FakeWebSocket(url, handlers);
  return {
    factory,
    latest: () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1],
    count: () => FakeWebSocket.instances.length,
  };
}

function makeClient(options = {}, callbacks = {}, factory) {
  return new BookRoomASRClient(
    {
      url: 'ws://127.0.0.1:15231/v1/audio/streaming/transcriptions',
      connectTimeout: 1000,
      startTimeout: 1000,
      ...options,
    },
    callbacks,
    factory,
  );
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const STARTED_MSG = {
  type: 'started',
  session_id: 'sess-1',
  engine: 'funasr-local',
  config: {},
};

/**
 * 连接并等待 open。
 * 注意：connect() 内部同步调用 wsFactory 创建 WebSocket 后，
 * 才等待 onOpen 触发 resolve。因此必须先发起 connect 拿到实例，
 * 再触发 simulateOpen，最后 await。
 */
async function connectAndOpen(client) {
  const connectPromise = client.connect();
  const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  ws.simulateOpen();
  await connectPromise;
}

/** 发送 START 并等待 STARTED 响应 */
async function startAndAwait(client, ws, config) {
  const startPromise = client.start(config);
  ws.simulateMessage(STARTED_MSG);
  await startPromise;
}

// ==================== 心跳保活 ====================

test('start 后按 heartbeatInterval 定时发送 PING', async () => {
  const { factory, latest } = makeFactory();
  const client = makeClient({ heartbeatInterval: 30 }, {}, factory);

  await connectAndOpen(client);
  const ws = latest();
  await startAndAwait(client, ws);
  assert.equal(client.getState(), 'started');

  // 等 2 个心跳周期，应至少收到 1 条 ping
  await sleep(70);
  const pings = ws.sentOfType('ping');
  assert.ok(pings.length >= 1, `应至少发送 1 条 PING，实际 ${pings.length}`);
  assert.ok(typeof pings[0].timestamp_ms === 'number');
});

test('heartbeatInterval<=0 时不发送 PING', async () => {
  const { factory, latest } = makeFactory();
  const client = makeClient({ heartbeatInterval: 0 }, {}, factory);

  await connectAndOpen(client);
  const ws = latest();
  await startAndAwait(client, ws);

  await sleep(50);
  assert.equal(ws.sentOfType('ping').length, 0);
});

test('收到 PONG 触发 onPong 回调并计算 RTT', async () => {
  const { factory, latest } = makeFactory();
  const pongs = [];
  const client = makeClient(
    { heartbeatInterval: 20 },
    { onPong: (msg, rttMs) => pongs.push({ msg, rttMs }) },
    factory,
  );

  await connectAndOpen(client);
  const ws = latest();
  await startAndAwait(client, ws);

  // 先等一次心跳发出，再回 PONG
  await sleep(40);
  assert.ok(ws.sentOfType('ping').length >= 1);
  ws.simulateMessage({ type: 'pong', session_id: 'sess-1', server_time_ms: 1 });

  assert.equal(pongs.length, 1);
  assert.ok(pongs[0].rttMs >= 0);
});

// ==================== 暂停 / 恢复 ====================

test('pause 发送 PAUSE，收到 paused 后状态切换', async () => {
  const { factory, latest } = makeFactory();
  const client = makeClient({}, {}, factory);

  await connectAndOpen(client);
  const ws = latest();
  await startAndAwait(client, ws);

  await client.pause();
  assert.equal(ws.sentOfType('pause').length, 1);

  ws.simulateMessage({ type: 'paused', session_id: 'sess-1', paused_at_ms: 0 });
  assert.equal(client.getState(), 'paused');
});

test('resume 发送 RESUME，收到 resumed 后状态回到 started', async () => {
  const { factory, latest } = makeFactory();
  const client = makeClient({}, {}, factory);

  await connectAndOpen(client);
  const ws = latest();
  await startAndAwait(client, ws);

  await client.pause();
  ws.simulateMessage({ type: 'paused', session_id: 'sess-1', paused_at_ms: 0 });

  await client.resume();
  assert.equal(ws.sentOfType('resume').length, 1);

  ws.simulateMessage({ type: 'resumed', session_id: 'sess-1', resumed_at_ms: 0 });
  assert.equal(client.getState(), 'started');
});

test('非 started 状态 pause 抛错', async () => {
  const { factory } = makeFactory();
  const client = makeClient({}, {}, factory);
  await assert.rejects(
    client.pause(),
    (err) => err.code === 'invalid_state',
  );
});

test('funasr 模式 pause/resume 抛错', async () => {
  const { factory, latest } = makeFactory();
  const client = makeClient({ mode: 'funasr' }, {}, factory);

  await connectAndOpen(client);
  await client.start(); // funasr 模式直接 started

  // funasr 模式不支持暂停/恢复：pause 在 started 状态即可拒绝，
  // resume 因状态非 paused 被拒绝（先于模式检查）
  await assert.rejects(client.pause(), /native mode/);
  await assert.rejects(client.resume(), /Cannot resume from state/);
});

// ==================== 指数退避重连 ====================

test('异常断开后指数退避重连并自动重发 START', async () => {
  const { factory, latest, count } = makeFactory();
  const attempts = [];
  const client = makeClient(
    { reconnect: 3, reconnectInterval: 10, reconnectMaxInterval: 1000, heartbeatInterval: 0 },
    { onReconnectAttempt: (attempt, delayMs) => attempts.push({ attempt, delayMs }) },
    factory,
  );

  await connectAndOpen(client);
  const ws1 = latest();
  await startAndAwait(client, ws1, { language: 'zh' });

  // 异常断开 → 触发重连
  ws1.simulateClose(1006, 'abnormal closure');
  assert.equal(attempts.length, 1);
  assert.equal(attempts[0].attempt, 1);
  // 退避区间：[10*0.75, 10*1.25]
  assert.ok(attempts[0].delayMs >= 7 && attempts[0].delayMs <= 13, `delay=${attempts[0].delayMs}`);

  // 等重连发生
  await sleep(60);
  assert.equal(count(), 2, '应创建第二个 WebSocket');

  const ws2 = latest();
  ws2.simulateOpen();
  await sleep(20);
  ws2.simulateMessage(STARTED_MSG);
  // 等待 start() 的 promise 恢复（setState 在微任务中执行）
  await sleep(20);

  // 自动恢复：重发了 START（携带原配置）
  const starts = ws2.sentOfType('start');
  assert.equal(starts.length, 1, '重连后应重发 START');
  assert.equal(starts[0].config.language, 'zh');
  assert.equal(client.getState(), 'started');
});

test('重连尝试失败达到上限后不再重连', async () => {
  const { factory, latest, count } = makeFactory();
  const client = makeClient(
    { reconnect: 1, reconnectInterval: 10, heartbeatInterval: 0 },
    {},
    factory,
  );

  await connectAndOpen(client);
  const ws1 = latest();
  await startAndAwait(client, ws1);

  ws1.simulateClose(1006, 'abnormal closure');
  await sleep(60);
  assert.equal(count(), 2, '第一次重连已创建新连接');

  // 重连连接未 open 即断开 → 达到上限，不再重连
  const ws2 = latest();
  ws2.simulateClose(1006, 'reconnect failed');
  await sleep(60);

  assert.equal(count(), 2, '不应再创建第 3 个连接');
  assert.equal(client.getState(), 'closed');
});

test('主动 close() 不触发重连', async () => {
  const { factory, latest, count } = makeFactory();
  const client = makeClient({ reconnect: 5, heartbeatInterval: 0 }, {}, factory);

  await connectAndOpen(client);
  const ws = latest();

  client.close();
  // close 内部 ws.close(1000) → 触发 onClose → handleClose → manuallyClosed → 不重连
  ws.simulateClose(1000, 'client closed');
  await sleep(50);

  assert.equal(count(), 1, '主动 close 不应创建新连接');
  assert.equal(client.getState(), 'closed');
});
