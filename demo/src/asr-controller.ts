/**
 * ASR 控制器：封装 BookRoomASRClient + MicCapturer 的完整生命周期
 *
 * 职责：
 * - 创建客户端与麦克风采集器
 * - 转发事件到 UI 回调
 * - 提供开始/停止/暂停/恢复的统一接口
 * - 资源清理
 */

import {
  BookRoomASRClient,
  ClientCallbacks,
  MicCapturer,
  MicCapturerOptions,
  StreamingSessionConfig,
  isMicSupported,
} from '@bookroom/audio-sdk';

/** ASR 控制器事件回调 */
export interface ASRControllerCallbacks {
  onStateChange: (state: string) => void;
  onStarted: (engine: string, sessionId: string) => void;
  onPartial: (text: string) => void;
  onFinal: (text: string, msg: unknown) => void;
  onError: (code: string, message: string) => void;
  onClosed: (reason: string) => void;
  onPong: (rttMs: number) => void;
  onReconnectAttempt: (attempt: number, delayMs: number) => void;
  onAudioChunk: (bytes: number) => void;
}

/** 启动参数 */
export interface StartParams {
  url: string;
  apiKey?: string;
  mode: 'native' | 'funasr';
  sessionConfig: StreamingSessionConfig;
  micOptions: MicCapturerOptions;
}

/**
 * ASR 控制器
 *
 * 单一职责：管理一个 ASR 会话的完整生命周期。
 * 一个控制器实例对应一次"开始-停止"周期，停止后不可复用。
 */
export class ASRController {
  private client: BookRoomASRClient | null = null;
  private mic: MicCapturer | null = null;
  private callbacks: ASRControllerCallbacks;
  private audioChunkCount = 0;

  constructor(callbacks: ASRControllerCallbacks) {
    this.callbacks = callbacks;
  }

  /** 检查浏览器是否支持 */
  static isSupported(): boolean {
    return isMicSupported();
  }

  /** 启动 ASR 会话 */
  async start(params: StartParams): Promise<void> {
    if (this.client !== null) {
      throw new Error('Controller already started');
    }
    if (!ASRController.isSupported()) {
      throw new Error(
        '当前浏览器不支持麦克风采集（需要 HTTPS 或 localhost）',
      );
    }

    const clientCallbacks: ClientCallbacks = {
      onConnected: () => {
        this.callbacks.onStateChange('connected');
      },
      onStarted: (msg) => {
        this.callbacks.onStarted(msg.engine, msg.session_id);
        this.callbacks.onStateChange('started');
        // 启动麦克风
        this.startMicInternal(params.micOptions).catch((err) => {
          this.callbacks.onError('mic_failed', err.message);
        });
      },
      onPartial: (text) => {
        this.callbacks.onPartial(text);
      },
      onFinal: (text, msg) => {
        this.callbacks.onFinal(text, msg);
      },
      onError: (err) => {
        this.callbacks.onError(err.code, err.message);
      },
      onClosed: (msg) => {
        this.callbacks.onClosed(msg.reason ?? 'unknown');
        this.callbacks.onStateChange('closed');
      },
      onStateChange: (state) => {
        this.callbacks.onStateChange(state);
      },
      onPong: (_pong, rttMs) => {
        this.callbacks.onPong(rttMs);
      },
      onReconnectAttempt: (attempt, delayMs) => {
        this.callbacks.onReconnectAttempt(attempt, delayMs);
      },
    };

    this.client = new BookRoomASRClient(
      {
        url: params.url,
        apiKey: params.apiKey,
        mode: params.mode,
        reconnect: 3,
        reconnectInterval: 1000,
        reconnectMaxInterval: 15000,
        connectTimeout: 8000,
        startTimeout: 60000,
        heartbeatInterval: 30000,
      },
      clientCallbacks,
    );

    this.audioChunkCount = 0;
    this.callbacks.onStateChange('connecting');

    await this.client.connect();
    await this.client.start(params.sessionConfig);
  }

  /** 内部启动麦克风采集 */
  private async startMicInternal(
    options: MicCapturerOptions,
  ): Promise<void> {
    if (this.client === null) {
      return;
    }

    this.mic = new MicCapturer(
      (chunk) => {
        if (this.client === null) {
          return;
        }
        try {
          this.client.sendAudio(chunk);
          this.audioChunkCount++;
          this.callbacks.onAudioChunk(chunk.byteLength);
        } catch (err) {
          // sendAudio 在非 started 状态会抛错，忽略
          if (err instanceof Error && err.message.includes('state')) {
            return;
          }
          this.callbacks.onError('send_failed', (err as Error).message);
        }
      },
      options,
    );

    await this.mic.start();
  }

  /** 暂停会话（仅 native 模式） */
  async pause(): Promise<void> {
    if (this.client === null) {
      return;
    }
    await this.client.pause();
  }

  /** 恢复会话（仅 native 模式） */
  async resume(): Promise<void> {
    if (this.client === null) {
      return;
    }
    await this.client.resume();
  }

  /** 停止会话 */
  async stop(): Promise<void> {
    // 先停麦克风
    if (this.mic !== null) {
      this.mic.stop();
      this.mic = null;
    }

    if (this.client !== null) {
      try {
        await this.client.stop();
      } catch {
        // 忽略停止错误
      }
    }
  }

  /** 关闭并释放所有资源 */
  close(): void {
    if (this.mic !== null) {
      this.mic.stop();
      this.mic = null;
    }
    if (this.client !== null) {
      this.client.close();
      this.client = null;
    }
  }

  /** 已发送的音频帧数 */
  getAudioChunkCount(): number {
    return this.audioChunkCount;
  }
}
