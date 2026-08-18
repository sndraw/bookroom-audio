/**
 * 浏览器麦克风采集辅助
 *
 * 使用 Web Audio API 采集麦克风音频，重采样为 16kHz mono 16bit PCM，
 * 通过回调持续输出 PCM chunks 供 ASR 客户端发送。
 *
 * 实现方式：AudioWorkletNode（推荐）+ ScriptProcessorNode（兜底）。
 */

import { AudioFormat, StreamingSessionConfig } from './types';

/** PCM chunk 回调 */
export type PCMChunkCallback = (chunk: ArrayBuffer) => void;

/** 麦克风采集器配置 */
export interface MicCapturerOptions {
  /** 目标采样率（默认 16000） */
  sampleRate?: number;
  /** 目标声道数（默认 1 = mono） */
  channelCount?: number;
  /** 每帧时长（毫秒，默认 100） */
  frameMs?: number;
  /** 是否启用回声消除（默认 true） */
  echoCancellation?: boolean;
  /** 是否启用噪声抑制（默认 true） */
  noiseSuppression?: boolean;
  /** 是否启用自动增益（默认 true） */
  autoGainControl?: boolean;
}

/** 麦克风采集器 */
export class MicCapturer {
  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private scriptNode: ScriptProcessorNode | null = null;
  private onChunk: PCMChunkCallback;
  private options: Required<MicCapturerOptions>;
  private isCapturing = false;

  constructor(
    onChunk: PCMChunkCallback,
    options: MicCapturerOptions = {},
  ) {
    this.onChunk = onChunk;
    this.options = {
      sampleRate: options.sampleRate ?? 16000,
      channelCount: options.channelCount ?? 1,
      frameMs: options.frameMs ?? 100,
      echoCancellation: options.echoCancellation ?? true,
      noiseSuppression: options.noiseSuppression ?? true,
      autoGainControl: options.autoGainControl ?? true,
    };
  }

  /** 启动麦克风采集 */
  async start(): Promise<void> {
    if (this.isCapturing) {
      throw new Error('MicCapturer already started');
    }
    if (typeof navigator === 'undefined' || !navigator.mediaDevices) {
      throw new Error(
        'getUserMedia not available: requires browser environment with HTTPS',
      );
    }

    // 请求麦克风权限
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: this.options.channelCount,
        echoCancellation: this.options.echoCancellation,
        noiseSuppression: this.options.noiseSuppression,
        autoGainControl: this.options.autoGainControl,
      },
    });

    // 创建 AudioContext（目标采样率）
    const AudioContextCtor: typeof AudioContext =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    this.audioContext = new AudioContextCtor({
      sampleRate: this.options.sampleRate,
    });

    this.sourceNode = this.audioContext.createMediaStreamSource(
      this.mediaStream,
    );

    // 优先使用 AudioWorklet（现代浏览器支持）
    const bufferSize = Math.floor(
      (this.options.sampleRate * this.options.frameMs) / 1000,
    );

    if (this.audioContext.audioWorklet !== undefined) {
      try {
        await this.setupAudioWorklet(bufferSize);
        return;
      } catch (err) {
        // AudioWorklet 不可用，回退到 ScriptProcessor
        console.warn(
          '[BookRoomASR] AudioWorklet unavailable, fallback to ScriptProcessor',
          err,
        );
      }
    }

    // 回退：ScriptProcessorNode（已废弃但兼容性好）
    this.setupScriptProcessor(bufferSize);
  }

  /** 停止采集 */
  stop(): void {
    this.isCapturing = false;

    if (this.workletNode !== null) {
      this.workletNode.port.postMessage({ type: 'stop' });
      this.workletNode.disconnect();
      this.workletNode = null;
    }

    if (this.scriptNode !== null) {
      this.scriptNode.disconnect();
      this.scriptNode = null;
    }

    if (this.sourceNode !== null) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }

    if (this.mediaStream !== null) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }

    if (this.audioContext !== null && this.audioContext.state !== 'closed') {
      this.audioContext.close();
      this.audioContext = null;
    }
  }

  /** 当前是否正在采集 */
  get isRunning(): boolean {
    return this.isCapturing;
  }

  // ==================== 内部方法 ====================

  /** AudioWorklet 设置 */
  private async setupAudioWorklet(bufferSize: number): Promise<void> {
    if (this.audioContext === null || this.sourceNode === null) {
      throw new Error('AudioContext not initialized');
    }

    // 注册内联 worklet（不依赖外部文件）
    const workletCode = `
      class PCMProcessor extends AudioWorkletProcessor {
        constructor() {
          super();
          this.bufferSize = ${bufferSize};
          this.buffer = new Float32Array(this.bufferSize);
          this.offset = 0;
          this.active = true;

          this.port.onmessage = (e) => {
            if (e.data && e.data.type === 'stop') {
              this.active = false;
            }
          };
        }

        process(inputs) {
          if (!this.active) return false;

          const input = inputs[0];
          if (!input || input.length === 0) return true;

          // 取第一个声道
          const channel = input[0];
          if (!channel) return true;

          for (let i = 0; i < channel.length; i++) {
            this.buffer[this.offset++] = channel[i];
            if (this.offset >= this.bufferSize) {
              // Float32 → Int16 PCM
              const pcm = new ArrayBuffer(this.bufferSize * 2);
              const view = new DataView(pcm);
              for (let j = 0; j < this.bufferSize; j++) {
                let s = Math.max(-1, Math.min(1, this.buffer[j]));
                s = s < 0 ? s * 0x8000 : s * 0x7fff;
                view.setInt16(j * 2, s | 0, true);
              }
              this.port.postMessage(pcm, [pcm]);
              this.offset = 0;
            }
          }
          return true;
        }
      }
      registerProcessor('pcm-processor', PCMProcessor);
    `;

    const blob = new Blob([workletCode], { type: 'application/javascript' });
    const url = URL.createObjectURL(blob);
    try {
      await this.audioContext.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }

    this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm-processor', {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: this.options.channelCount,
    });

    this.workletNode.port.onmessage = (ev: MessageEvent) => {
      if (ev.data instanceof ArrayBuffer) {
        this.onChunk(ev.data);
      }
    };

    this.sourceNode.connect(this.workletNode);
    this.isCapturing = true;
  }

  /** ScriptProcessor 兜底实现 */
  private setupScriptProcessor(bufferSize: number): void {
    if (this.audioContext === null || this.sourceNode === null) {
      throw new Error('AudioContext not initialized');
    }

    // bufferSize 必须是 2 的幂次方：256, 512, 1024, 2048, 4096, 8192, 16384
    const validSizes = [256, 512, 1024, 2048, 4096, 8192, 16384];
    let scriptBufferSize = 4096;
    for (const size of validSizes) {
      if (size >= bufferSize) {
        scriptBufferSize = size;
        break;
      }
    }

    this.scriptNode = this.audioContext.createScriptProcessor(
      scriptBufferSize,
      this.options.channelCount,
      this.options.channelCount,
    );

    this.scriptNode.onaudioprocess = (ev: AudioProcessingEvent) => {
      if (!this.isCapturing) return;

      const channelData = ev.inputBuffer.getChannelData(0);
      const length = channelData.length;
      const pcm = new ArrayBuffer(length * 2);
      const view = new DataView(pcm);

      for (let i = 0; i < length; i++) {
        let s = Math.max(-1, Math.min(1, channelData[i]));
        s = s < 0 ? s * 0x8000 : s * 0x7fff;
        view.setInt16(i * 2, s | 0, true);
      }

      this.onChunk(pcm);
    };

    this.sourceNode.connect(this.scriptNode);
    // ScriptProcessor 必须连接 destination 才能触发 onaudioprocess
    this.scriptNode.connect(this.audioContext.destination);
    this.isCapturing = true;
  }
}

/**
 * 创建麦克风采集器并连接到 ASR 客户端的便捷方法
 *
 * 使用示例：
 * ```ts
 * const client = new BookRoomASRClient({...});
 * await client.connect();
 * await client.start({ engine: 'funasr-local' });
 * const mic = await startMicToClient(client);
 * // ...用户说话...
 * mic.stop();
 * await client.stop();
 * ```
 */
export async function startMicToClient(
  client: { sendAudio: (data: ArrayBuffer) => void },
  options?: MicCapturerOptions,
): Promise<MicCapturer> {
  const mic = new MicCapturer(
    (chunk) => client.sendAudio(chunk),
    options,
  );
  await mic.start();
  return mic;
}

/**
 * 从 MediaStreamConfig 生成 MicCapturerOptions
 * （保留 audio_format/sample_rate 一致性）
 */
export function micOptionsFromConfig(
  config: Partial<StreamingSessionConfig>,
): MicCapturerOptions {
  return {
    sampleRate: config.sample_rate ?? 16000,
    channelCount: 1, // 流式 ASR 固定 mono
    frameMs: 100,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  };
}

/** 检测浏览器是否支持麦克风采集 */
export function isMicSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    typeof navigator.mediaDevices !== 'undefined' &&
    typeof navigator.mediaDevices.getUserMedia === 'function' &&
    typeof AudioContext !== 'undefined'
  );
}

/** 检测音频格式是否支持 */
export function isAudioFormatSupported(format: AudioFormat): boolean {
  // PCM/WAV 在所有环境都支持
  if (format === 'pcm' || format === 'wav') return true;
  // 其他格式由服务端解码
  return true;
}
