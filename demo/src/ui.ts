/**
 * UI 控制器：封装 DOM 操作、日志输出、状态显示
 *
 * 职责：
 * - 缓存所有 DOM 元素引用
 * - 提供日志、状态、结果更新方法
 * - 提供 toast 提示
 */

import { ClientState, FinalMessage, StartedMessage } from '@bookroom/audio-sdk';

/** 日志条目类型 */
export type LogType =
  | 'info'
  | 'partial'
  | 'final'
  | 'error'
  | 'audio'
  | 'state'
  | 'reconnect';

/** 状态徽章样式映射 */
const STATE_BADGE_CLASS: Record<ClientState, string> = {
  idle: 'state-badge--idle',
  connecting: 'state-badge--connecting',
  connected: 'state-badge--connected',
  started: 'state-badge--started',
  paused: 'state-badge--paused',
  stopping: 'state-badge--stopping',
  closed: 'state-badge--closed',
};

/** UI 元素引用集合 */
export interface UIElements {
  // 配置区
  url: HTMLInputElement;
  apiKey: HTMLInputElement;
  mode: HTMLSelectElement;
  engine: HTMLSelectElement;
  chunkSize: HTMLSelectElement;
  silence: HTMLSelectElement;
  hotwords: HTMLTextAreaElement;

  // 控制按钮
  btnStart: HTMLButtonElement;
  btnStop: HTMLButtonElement;
  btnPause: HTMLButtonElement;
  btnResume: HTMLButtonElement;
  btnClear: HTMLButtonElement;

  // 状态显示
  stateBadge: HTMLSpanElement;
  engineInfo: HTMLSpanElement;
  rttInfo: HTMLSpanElement;

  // 结果区
  partial: HTMLDivElement;
  finalList: HTMLDivElement;
  finalCount: HTMLSpanElement;

  // 日志
  log: HTMLDivElement;
  logAudio: HTMLInputElement;
}

/** 获取所有 UI 元素引用 */
export function getUIElements(): UIElements {
  const get = <T extends HTMLElement>(id: string): T => {
    const el = document.getElementById(id);
    if (!el) {
      throw new Error(`UI element not found: ${id}`);
    }
    return el as T;
  };

  return {
    url: get<HTMLInputElement>('url'),
    apiKey: get<HTMLInputElement>('apiKey'),
    mode: get<HTMLSelectElement>('mode'),
    engine: get<HTMLSelectElement>('engine'),
    chunkSize: get<HTMLSelectElement>('chunkSize'),
    silence: get<HTMLSelectElement>('silence'),
    hotwords: get<HTMLTextAreaElement>('hotwords'),

    btnStart: get<HTMLButtonElement>('btn-start'),
    btnStop: get<HTMLButtonElement>('btn-stop'),
    btnPause: get<HTMLButtonElement>('btn-pause'),
    btnResume: get<HTMLButtonElement>('btn-resume'),
    btnClear: get<HTMLButtonElement>('btn-clear'),

    stateBadge: get<HTMLSpanElement>('state-badge'),
    engineInfo: get<HTMLSpanElement>('engine-info'),
    rttInfo: get<HTMLSpanElement>('rtt-info'),

    partial: get<HTMLDivElement>('partial'),
    finalList: get<HTMLDivElement>('final-list'),
    finalCount: get<HTMLSpanElement>('final-count'),

    log: get<HTMLDivElement>('log'),
    logAudio: get<HTMLInputElement>('log-audio'),
  };
}

/** UI 状态更新参数 */
export interface StateUpdate {
  state: ClientState;
  engine?: string;
  sessionId?: string;
}

/** 更新状态徽章和元信息 */
export function updateStateUI(els: UIElements, update: StateUpdate): void {
  els.stateBadge.textContent = update.state;
  els.stateBadge.className = `state-badge ${STATE_BADGE_CLASS[update.state]}`;

  if (update.engine) {
    els.engineInfo.textContent = `engine=${update.engine}`;
  }
  if (update.state === 'closed' || update.state === 'idle') {
    els.engineInfo.textContent = '';
    els.rttInfo.textContent = '';
  }
}

/** 更新 RTT 显示 */
export function updateRttUI(els: UIElements, rttMs: number): void {
  if (rttMs <= 0) {
    els.rttInfo.textContent = '';
    return;
  }
  els.rttInfo.textContent = `RTT=${rttMs}ms`;
}

/** 按钮可用性控制参数 */
export interface ButtonState {
  started: boolean;
  paused: boolean;
}

/** 根据 ASR 状态控制按钮可用性 */
export function updateButtonsUI(els: UIElements, state: ClientState): void {
  const isStarted = state === 'started';
  const isPaused = state === 'paused';
  const isStopping = state === 'stopping';
  const isActive = isStarted || isPaused;

  els.btnStart.disabled = isActive || isStopping
    || state === 'connecting' || state === 'connected';
  els.btnStop.disabled = !isActive;
  els.btnPause.disabled = !isStarted;
  els.btnResume.disabled = !isPaused;
}

/** 添加一条日志 */
export function appendLog(
  els: UIElements,
  type: LogType,
  message: string,
): void {
  // 音频日志默认隐藏，除非用户勾选
  if (type === 'audio' && !els.logAudio.checked) {
    return;
  }

  const entry = document.createElement('div');
  entry.className = `log-entry log-entry--${type}`;

  const time = document.createElement('span');
  time.className = 'log-entry__time';
  time.textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false });

  const tag = document.createElement('span');
  tag.className = 'log-entry__tag';
  tag.textContent = `[${type.toUpperCase()}]`;

  const msg = document.createElement('span');
  msg.className = 'log-entry__msg';
  msg.textContent = message;

  entry.append(time, tag, msg);
  els.log.appendChild(entry);

  // 限制日志条数，避免内存增长
  if (els.log.children.length > 500) {
    els.log.removeChild(els.log.firstChild!);
  }

  els.log.scrollTop = els.log.scrollHeight;
}

/** 更新 PARTIAL 显示 */
export function updatePartialUI(els: UIElements, text: string): void {
  els.partial.textContent = text || '（等待识别...）';
}

/** 添加一条 FINAL 结果 */
export function appendFinalUI(
  els: UIElements,
  msg: FinalMessage,
): void {
  // 清空"等待识别..."占位
  if (els.finalList.textContent.includes('等待')) {
    els.finalList.innerHTML = '';
  }

  const item = document.createElement('div');
  item.className = 'final-item';

  const meta = document.createElement('div');
  meta.className = 'final-item__meta';
  const duration = msg.end_ms - msg.start_ms;
  meta.textContent = `#${msg.sentence_id} · ${(duration / 1000).toFixed(1)}s`;

  const text = document.createElement('div');
  text.className = 'final-item__text';
  text.textContent = msg.text;

  item.append(meta, text);
  els.finalList.appendChild(item);

  // 更新计数
  const count = els.finalList.querySelectorAll('.final-item').length;
  els.finalCount.textContent = String(count);

  // 清空 PARTIAL 显示
  els.partial.textContent = '（等待识别...）';

  // 自动滚动到底部
  els.finalList.scrollTop = els.finalList.scrollHeight;
}

/** 清空所有结果和日志 */
export function clearResultsUI(els: UIElements): void {
  els.partial.textContent = '（等待识别...）';
  els.finalList.innerHTML = '';
  els.finalCount.textContent = '0';
  els.log.innerHTML = '';
}

/** 记录 STARTED 消息 */
export function logStarted(els: UIElements, msg: StartedMessage): void {
  appendLog(els, 'info',
    `会话已启动：session=${msg.session_id} engine=${msg.engine}`);
}
