/**
 * bookroom-audio 流式 ASR 客户端 SDK 类型定义
 *
 * 协议参考：
 * - 原生端点: ws://host:port/v1/audio/streaming/transcriptions
 * - FunASR 兼容端点: ws://host:port/v1/audio/streaming/funasr
 */

// ==================== 引擎与格式枚举 ====================

/** 流式 ASR 引擎类型 */
export type StreamingASREngine =
  | 'funasr-server'
  | 'funasr-local'
  | 'sensevoice-local';

/** 音频输入格式 */
export type AudioFormat =
  | 'pcm'
  | 'wav'
  | 'mp3'
  | 'opus'
  | 'speex'
  | 'aac'
  | 'amr';

/** 错误码 */
export type ErrorCode =
  | 'auth_failed'
  | 'invalid_config'
  | 'unsupported_engine'
  | 'unsupported_format'
  | 'engine_unavailable'
  | 'audio_decode_failed'
  | 'internal_error'
  | 'session_not_found'
  | 'connect_failed'
  | 'connect_timeout'
  | 'start_timeout'
  | 'connection_closed'
  | 'reconnect_failed'
  | 'invalid_state'
  | 'not_connected';

/** 客户端消息类型 */
export type ClientMessageType = 'start' | 'audio' | 'stop';

/** 服务端消息类型 */
export type ServerMessageType =
  | 'started'
  | 'partial'
  | 'final'
  | 'error'
  | 'closed';

// ==================== 会话配置 ====================

/** 流式识别会话配置 */
export interface StreamingSessionConfig {
  /** 引擎类型，未指定则使用服务端默认值 */
  engine?: StreamingASREngine;
  /** 语言代码 */
  language?: string;
  /** 音频输入格式 */
  audio_format?: AudioFormat;
  /** 采样率 */
  sample_rate?: number;
  /** 启用标点恢复 */
  enable_punctuation?: boolean;
  /** 启用服务端 VAD 自动断句 */
  enable_vad?: boolean;
  /** 启用逆文本归一化 */
  enable_itn?: boolean;
  /** 启用说话人分离 */
  enable_speaker_diarization?: boolean;
  /** 启用情感识别（仅 SenseVoice） */
  enable_emotion?: boolean;
  /** 热词权重映射 */
  hotwords?: Record<string, number>;
  /** 流式分块 [左回溯, 当前, 右前瞻]，默认 [5,10,5] */
  chunk_size?: [number, number, number];
  /** VAD 静音断句阈值（毫秒），200-6000 */
  max_sentence_silence_ms?: number;
}

/** 客户端连接选项 */
export interface ClientOptions {
  /** WebSocket URL，如 ws://127.0.0.1:15231/v1/audio/streaming/transcriptions */
  url: string;
  /** API Key，服务端未配置鉴权时可省略 */
  apiKey?: string;
  /** 协议模式：native=bookroom-audio 原生，funasr=FunASR 兼容 */
  mode?: 'native' | 'funasr';
  /** WebSocket 子协议（可选） */
  subprotocol?: string;
  /** 自动重连次数，默认 0（不重连） */
  reconnect?: number;
  /** 重连间隔（毫秒），默认 1000 */
  reconnectInterval?: number;
  /** 连接超时（毫秒），默认 10000 */
  connectTimeout?: number;
  /** START 消息等待超时（毫秒），默认 30000 */
  startTimeout?: number;
}

// ==================== 服务端消息 ====================

/** STARTED 消息 */
export interface StartedMessage {
  type: 'started';
  session_id: string;
  engine: string;
  config: Record<string, unknown>;
}

/**
 * PARTIAL 中间结果
 *
 * 语义说明（替换式）：`text` 字段为"到目前为止的整句识别结果"，
 * 后到的 PARTIAL 会覆盖前一条。客户端直接用最新 `text` 替换当前显示即可，
 * 无需自己拼接增量文本。
 */
export interface PartialMessage {
  type: 'partial';
  session_id: string;
  text: string;
  is_final: false;
  sentence_id: number;
  timestamp_ms: number;
}

/** 词级时间戳 */
export interface WordInfo {
  text: string;
  start_ms: number;
  end_ms: number;
  punctuation?: string;
}

/** FINAL 句末最终结果 */
export interface FinalMessage {
  type: 'final';
  session_id: string;
  text: string;
  is_final: true;
  sentence_id: number;
  start_ms: number;
  end_ms: number;
  speaker?: number;
  emotion?: string;
  words?: WordInfo[];
}

/** ERROR 消息 */
export interface ErrorMessage {
  type: 'error';
  session_id?: string;
  code: ErrorCode;
  message: string;
}

/** CLOSED 消息 */
export interface ClosedMessage {
  type: 'closed';
  session_id: string;
  reason?: string;
}

/** 服务端消息联合类型 */
export type ServerMessage =
  | StartedMessage
  | PartialMessage
  | FinalMessage
  | ErrorMessage
  | ClosedMessage;

// ==================== 客户端状态 ====================

/** 客户端连接状态 */
export type ClientState =
  | 'idle'        // 未连接
  | 'connecting'  // 连接中
  | 'connected'   // 已连接，未启动会话
  | 'started'     // 会话已启动，可发送音频
  | 'stopping'    // 已发 STOP，等待 FINAL
  | 'closed';     // 已关闭

/** 事件回调集合 */
export interface ClientCallbacks {
  /** 连接建立 */
  onConnected?: () => void;
  /** 会话已启动，参数为 STARTED 消息 */
  onStarted?: (msg: StartedMessage) => void;
  /** 中间识别结果 */
  onPartial?: (text: string, msg: PartialMessage) => void;
  /** 句末最终结果 */
  onFinal?: (text: string, msg: FinalMessage) => void;
  /** 错误 */
  onError?: (msg: ErrorMessage) => void;
  /** 会话关闭 */
  onClosed?: (msg: ClosedMessage) => void;
  /** 状态变化 */
  onStateChange?: (state: ClientState) => void;
}

// ==================== FunASR 兼容模式消息 ====================

/** FunASR 协议初始化消息（客户端 → 服务端） */
export interface FunASRInitMessage {
  mode: 'online' | 'offline' | '2pass';
  chunk_size: [number, number, number];
  wav_name: string;
  is_speaking: boolean;
  hotwords?: string;
  itn?: boolean;
  audio_fs?: number;
  wav_format?: string;
}

/** FunASR 协议响应消息（服务端 → 客户端） */
export interface FunASRResponseMessage {
  mode: '2pass-online' | '2pass-offline' | 'online' | 'offline' | '';
  wav_name: string;
  text: string;
  is_final: boolean;
  timestamp?: string;
  stamp_sents?: unknown;
  error?: boolean;
  error_code?: string;
}
