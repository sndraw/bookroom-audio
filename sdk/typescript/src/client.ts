/**
 * bookroom-audio 流式 ASR 客户端核心
 *
 * 平台无关实现，支持两种协议模式：
 * - native: bookroom-audio 原生协议（START/AUDIO/STOP/PARTIAL/FINAL/CLOSED）
 * - funasr: FunASR serve_realtime_ws.py 兼容协议（init/binary/is_speaking=false）
 *
 * 增强能力：
 * - 心跳保活（PING/PONG）
 * - 暂停/恢复（PAUSE/RESUME，仅 native 模式）
 * - 指数退避重连（带抖动，避免雪崩）
 * - 重连后自动恢复会话（重发 START）
 */

import {
  ClientCallbacks,
  ClientOptions,
  ClientState,
  FinalMessage,
  PartialMessage,
  ServerMessage,
  StartedMessage,
  StreamingSessionConfig,
  ErrorMessage,
  ClosedMessage,
  PongMessage,
  PausedMessage,
  ResumedMessage,
  FunASRInitMessage,
  FunASRResponseMessage,
} from './types';
import {
  IWebSocket,
  WebSocketFactory,
  defaultWebSocketFactory,
} from './websocket';

/** 默认配置值 */
const DEFAULT_OPTIONS: Required<Pick<ClientOptions, 'mode' | 'reconnect' | 'reconnectInterval' | 'reconnectMaxInterval' | 'connectTimeout' | 'startTimeout' | 'heartbeatInterval'>> = {
  mode: 'native',
  reconnect: 0,
  reconnectInterval: 1000,
  reconnectMaxInterval: 30000,
  connectTimeout: 10000,
  startTimeout: 30000,
  heartbeatInterval: 30000,
};

const DEFAULT_SESSION_CONFIG: StreamingSessionConfig = {
  language: 'zh',
  audio_format: 'pcm',
  sample_rate: 16000,
  enable_punctuation: true,
  enable_vad: true,
  enable_itn: true,
  enable_speaker_diarization: false,
  enable_emotion: false,
  max_sentence_silence_ms: 1300,
};

/** 客户端错误 */
export class ASRClientError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = 'ASRClientError';
  }
}

/** bookroom-audio 流式 ASR 客户端 */
export class BookRoomASRClient {
  private options: ClientOptions & typeof DEFAULT_OPTIONS;
  private callbacks: ClientCallbacks = {};
  private wsFactory: WebSocketFactory;
  private ws: IWebSocket | null = null;
  private state: ClientState = 'idle';
  private reconnectAttempts = 0;
  private started = false;
  private startPromise: Promise<StartedMessage> | null = null;
  private startResolve: ((msg: StartedMessage) => void) | null = null;
  private startReject: ((err: Error) => void) | null = null;
  private startTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private lastPingTime = 0;
  // 用户主动关闭标志：区分主动 close 与异常断开，决定是否重连
  private manuallyClosed = false;
  // 最近一次 start 时的配置，用于重连后自动恢复会话
  private lastStartConfig: Partial<StreamingSessionConfig> | null = null;

  constructor(
    options: ClientOptions,
    callbacks: ClientCallbacks = {},
    wsFactory: WebSocketFactory = defaultWebSocketFactory,
  ) {
    this.options = { ...DEFAULT_OPTIONS, ...options };
    this.callbacks = callbacks;
    this.wsFactory = wsFactory;
  }

  /** 注册回调（可在构造后覆盖） */
  setCallbacks(callbacks: ClientCallbacks): void {
    this.callbacks = { ...this.callbacks, ...callbacks };
  }

  /** 获取当前状态 */
  getState(): ClientState {
    return this.state;
  }

  /** 建立连接（不发送 START） */
  async connect(): Promise<void> {
    if (this.state !== 'idle' && this.state !== 'closed') {
      throw new ASRClientError(
        'invalid_state',
        `Cannot connect from state: ${this.state}`,
      );
    }

    this.setState('connecting');

    return new Promise<void>((resolve, reject) => {
      let connectTimer: ReturnType<typeof setTimeout> | null = null;
      let settled = false;

      const cleanup = (): void => {
        if (connectTimer !== null) {
          clearTimeout(connectTimer);
          connectTimer = null;
        }
      };

      connectTimer = setTimeout(() => {
        if (settled) return;
        settled = true;
        cleanup();
        this.ws?.close();
        reject(
          new ASRClientError(
            'connect_timeout',
            `Connect timeout after ${this.options.connectTimeout}ms`,
          ),
        );
      }, this.options.connectTimeout);

      // 构造带 token 的 URL
      const url = this.buildUrl();

      this.ws = this.wsFactory(
        url,
        {
          onOpen: () => {
            if (settled) return;
            settled = true;
            cleanup();
            this.setState('connected');
            this.reconnectAttempts = 0;
            this.callbacks.onConnected?.();
            resolve();
          },
          onMessage: (data) => this.handleMessage(data),
          onClose: (code, reason) => {
            cleanup();
            this.handleClose(code, reason);
          },
          onError: (err) => {
            cleanup();
            if (!settled) {
              settled = true;
              reject(
                new ASRClientError('connect_failed', err.message),
              );
            } else {
              this.callbacks.onError?.({
                type: 'error',
                code: 'internal_error',
                message: err.message,
              });
            }
          },
        },
        this.options.subprotocol,
      );
    });
  }

  /** 启动会话（发送 START 或 FunASR 初始化消息） */
  async start(config?: Partial<StreamingSessionConfig>): Promise<StartedMessage> {
    if (this.state !== 'connected') {
      throw new ASRClientError(
        'invalid_state',
        `Cannot start from state: ${this.state}, must be connected`,
      );
    }
    if (this.started) {
      throw new ASRClientError(
        'invalid_state',
        'Session already started',
      );
    }

    const fullConfig: StreamingSessionConfig = {
      ...DEFAULT_SESSION_CONFIG,
      ...config,
    };
    this.lastStartConfig = config ?? null;

    // native 模式等待 STARTED 响应；funasr 模式不返回 STARTED
    if (this.options.mode === 'native') {
      this.startPromise = new Promise<StartedMessage>((resolve, reject) => {
        this.startResolve = resolve;
        this.startReject = reject;
        this.startTimer = setTimeout(() => {
          if (this.startReject) {
            this.startReject(
              new ASRClientError(
                'start_timeout',
                `STARTED timeout after ${this.options.startTimeout}ms`,
              ),
            );
            this.startResolve = null;
            this.startReject = null;
          }
        }, this.options.startTimeout);
      });
    }

    // 发送初始化消息
    let initPayload: string;
    if (this.options.mode === 'funasr') {
      initPayload = this.buildFunASRInitMessage(fullConfig);
    } else {
      initPayload = JSON.stringify({
        type: 'start',
        config: fullConfig,
      });
    }

    this.send(initPayload);
    this.started = true;

    if (this.options.mode === 'native' && this.startPromise) {
      try {
        const started = await this.startPromise;
        this.setState('started');
        this.startHeartbeat();
        return started;
      } catch (err) {
        this.started = false;
        throw err;
      } finally {
        if (this.startTimer !== null) {
          clearTimeout(this.startTimer);
          this.startTimer = null;
        }
        this.startPromise = null;
        this.startResolve = null;
        this.startReject = null;
      }
    }

    // funasr 模式：直接进入 started 状态
    this.setState('started');
    this.startHeartbeat();
    return {
      type: 'started',
      session_id: 'funasr-compat',
      engine: fullConfig.engine ?? 'funasr-local',
      config: fullConfig as Record<string, unknown>,
    };
  }

  /** 发送音频数据（PCM 16kHz mono 16bit） */
  sendAudio(data: ArrayBuffer | ArrayBufferView | Uint8Array): void {
    if (this.state !== 'started') {
      throw new ASRClientError(
        'invalid_state',
        `Cannot send audio from state: ${this.state}`,
      );
    }
    this.send(data);
  }

  /** 暂停会话（暂停期间服务端丢弃音频，仅 native 模式） */
  async pause(): Promise<void> {
    if (this.state !== 'started') {
      throw new ASRClientError(
        'invalid_state',
        `Cannot pause from state: ${this.state}`,
      );
    }
    if (this.options.mode === 'funasr') {
      throw new ASRClientError(
        'invalid_state',
        'PAUSE/RESUME only supported in native mode',
      );
    }
    this.send(JSON.stringify({ type: 'pause' }));
  }

  /** 恢复会话（仅 native 模式） */
  async resume(): Promise<void> {
    if (this.state !== 'paused') {
      throw new ASRClientError(
        'invalid_state',
        `Cannot resume from state: ${this.state}`,
      );
    }
    if (this.options.mode === 'funasr') {
      throw new ASRClientError(
        'invalid_state',
        'PAUSE/RESUME only supported in native mode',
      );
    }
    this.send(JSON.stringify({ type: 'resume' }));
  }

  /** 停止会话（发送 STOP 或 is_speaking=false） */
  async stop(): Promise<void> {
    if (this.state !== 'started' && this.state !== 'paused') {
      return;
    }

    this.setState('stopping');
    this.stopHeartbeat();

    let stopPayload: string;
    if (this.options.mode === 'funasr') {
      stopPayload = JSON.stringify({ is_speaking: false });
    } else {
      stopPayload = JSON.stringify({ type: 'stop' });
    }

    this.send(stopPayload);
  }

  /** 关闭连接（不重连） */
  close(): void {
    this.manuallyClosed = true;
    this.started = false;
    this.stopHeartbeat();
    if (this.ws !== null && this.ws.readyState !== this.ws.CLOSED) {
      this.ws.close(1000, 'client closed');
    }
    this.setState('closed');
  }

  // ==================== 心跳 ====================

  /** 启动心跳定时器 */
  private startHeartbeat(): void {
    if (this.options.heartbeatInterval <= 0) return;
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.state !== 'started' && this.state !== 'paused') {
        return;
      }
      this.lastPingTime = Date.now();
      this.send(JSON.stringify({
        type: 'ping',
        timestamp_ms: this.lastPingTime,
      }));
    }, this.options.heartbeatInterval);
  }

  /** 停止心跳定时器 */
  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  // ==================== 内部方法 ====================

  /** 构造带 token 的 URL */
  private buildUrl(): string {
    if (!this.options.apiKey) {
      return this.options.url;
    }
    const separator = this.options.url.includes('?') ? '&' : '?';
    return `${this.options.url}${separator}token=${encodeURIComponent(
      this.options.apiKey,
    )}`;
  }

  /** 构造 FunASR 兼容初始化消息 */
  private buildFunASRInitMessage(
    config: StreamingSessionConfig,
  ): string {
    const mode = config.engine === 'sensevoice-local' ? 'offline' : '2pass';
    const chunkSize = config.chunk_size ?? [5, 10, 5];
    const hotwords = config.hotwords
      ? JSON.stringify(config.hotwords)
      : undefined;

    const init: FunASRInitMessage = {
      mode,
      chunk_size: chunkSize,
      wav_name: 'microphone',
      is_speaking: true,
      itn: config.enable_itn ?? true,
      audio_fs: config.sample_rate ?? 16000,
      wav_format: config.audio_format ?? 'pcm',
      ...(hotwords !== undefined ? { hotwords } : {}),
    };
    return JSON.stringify(init);
  }

  /** 发送数据到 WebSocket */
  private send(data: string | ArrayBuffer | ArrayBufferView): void {
    if (this.ws === null) {
      throw new ASRClientError('not_connected', 'WebSocket is null');
    }
    this.ws.send(data as string | ArrayBufferLike | ArrayBufferView);
  }

  /** 处理 WebSocket 收到的消息 */
  private handleMessage(data: string | ArrayBuffer | Uint8Array): void {
    // 二进制消息忽略（流式 ASR 服务端不发二进制）
    if (typeof data !== 'string') {
      return;
    }

    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(data);
    } catch {
      return;
    }

    if (this.options.mode === 'funasr') {
      this.handleFunASRMessage(msg);
    } else {
      this.handleNativeMessage(msg);
    }
  }

  /** 处理 native 协议消息 */
  private handleNativeMessage(msg: Record<string, unknown>): void {
    const type = msg.type as ServerMessage['type'];

    switch (type) {
      case 'started': {
        const started = msg as unknown as StartedMessage;
        if (this.startResolve) {
          this.startResolve(started);
        }
        this.callbacks.onStarted?.(started);
        break;
      }
      case 'partial': {
        const partial = msg as unknown as PartialMessage;
        this.callbacks.onPartial?.(partial.text, partial);
        break;
      }
      case 'final': {
        const finalMsg = msg as unknown as FinalMessage;
        this.callbacks.onFinal?.(finalMsg.text, finalMsg);
        break;
      }
      case 'error': {
        const err = msg as unknown as ErrorMessage;
        if (this.startReject) {
          this.startReject(
            new ASRClientError(err.code, err.message),
          );
          this.startResolve = null;
          this.startReject = null;
        }
        this.callbacks.onError?.(err);
        break;
      }
      case 'closed': {
        const closed = msg as unknown as ClosedMessage;
        this.callbacks.onClosed?.(closed);
        this.setState('closed');
        break;
      }
      case 'pong': {
        const pong = msg as unknown as PongMessage;
        const rttMs = this.lastPingTime > 0
          ? Date.now() - this.lastPingTime
          : 0;
        this.callbacks.onPong?.(pong, rttMs);
        break;
      }
      case 'paused': {
        const paused = msg as unknown as PausedMessage;
        this.setState('paused');
        this.callbacks.onPaused?.(paused);
        break;
      }
      case 'resumed': {
        const resumed = msg as unknown as ResumedMessage;
        this.setState('started');
        this.callbacks.onResumed?.(resumed);
        break;
      }
      default:
        break;
    }
  }

  /** 处理 FunASR 协议响应 */
  private handleFunASRMessage(msg: Record<string, unknown>): void {
    const resp = msg as unknown as FunASRResponseMessage;

    // 错误消息
    if (resp.error) {
      const err: ErrorMessage = {
        type: 'error',
        code: (resp.error_code as ErrorMessage['code']) ?? 'internal_error',
        message: resp.text,
      };
      this.callbacks.onError?.(err);
      return;
    }

    // 转换为 native 消息格式，统一回调
    if (resp.is_final) {
      const finalMsg: FinalMessage = {
        type: 'final',
        session_id: 'funasr-compat',
        text: resp.text,
        is_final: true,
        sentence_id: 0,
        start_ms: 0,
        end_ms: 0,
        words: [],
      };
      this.callbacks.onFinal?.(finalMsg.text, finalMsg);
    } else {
      const partial: PartialMessage = {
        type: 'partial',
        session_id: 'funasr-compat',
        text: resp.text,
        is_final: false,
        sentence_id: 0,
        timestamp_ms: 0,
      };
      this.callbacks.onPartial?.(partial.text, partial);
    }
  }

  /** 处理 WebSocket 关闭 */
  private handleClose(code: number, reason: string): void {
    // 取消未完成的 start promise
    if (this.startReject) {
      this.startReject(
        new ASRClientError(
          'connection_closed',
          `Connection closed before STARTED: ${code} ${reason}`,
        ),
      );
      this.startResolve = null;
      this.startReject = null;
    }

    const wasActive = this.state === 'started'
      || this.state === 'paused'
      || this.state === 'stopping';
    this.started = false;
    this.stopHeartbeat();

    // 触发 closed 回调（如果之前是活跃状态）
    if (wasActive) {
      this.callbacks.onClosed?.({
        type: 'closed',
        session_id: 'unknown',
        reason: `${code}: ${reason}`,
      });
    }

    // 用户主动 close 时不重连
    if (this.manuallyClosed) {
      this.setState('closed');
      return;
    }

    // 指数退避重连
    if (
      this.options.reconnect > 0
      && this.reconnectAttempts < this.options.reconnect
    ) {
      // 先重置为 closed，使 connect() 的状态校验通过
      this.setState('closed');
      this.reconnectAttempts++;
      const delayMs = this.computeReconnectDelay();
      this.callbacks.onReconnectAttempt?.(
        this.reconnectAttempts,
        delayMs,
      );
      setTimeout(() => {
        this.reconnectAndRecover().catch((err) => {
          this.callbacks.onError?.({
            type: 'error',
            code: 'reconnect_failed',
            message: err.message,
          });
        });
      }, delayMs);
      return;
    }

    this.setState('closed');
  }

  /** 计算指数退避延迟（带 ±25% 抖动，防止雪崩） */
  private computeReconnectDelay(): number {
    const base = this.options.reconnectInterval;
    const max = this.options.reconnectMaxInterval;
    // 指数退避：base * 2^(attempt-1)
    const exponential = base * Math.pow(2, this.reconnectAttempts - 1);
    const capped = Math.min(exponential, max);
    // 抖动：±25% 防止雪崩
    const jitter = capped * (0.75 + Math.random() * 0.5);
    return Math.round(jitter);
  }

  /** 重连并尝试恢复会话（重发 START，cache 已丢失） */
  private async reconnectAndRecover(): Promise<void> {
    await this.connect();
    if (this.lastStartConfig !== null) {
      await this.start(this.lastStartConfig);
    }
  }

  /** 更新状态并触发回调 */
  private setState(state: ClientState): void {
    if (this.state === state) return;
    this.state = state;
    this.callbacks.onStateChange?.(state);
  }
}
