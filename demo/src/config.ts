/**
 * Demo 配置常量
 *
 * 注意：依据项目规范，不在代码中硬编码服务端地址。
 * URL 默认值从当前页面 location 推导，由用户在 UI 中确认或修改。
 */

/** Demo 默认端口 */
export const DEMO_PORT = 5180;

/** 服务端默认端口（用于从 location.host 推导 WebSocket URL） */
export const SERVER_DEFAULT_PORT = 15231;

/** 服务端 WebSocket 路径 */
export const SERVER_WS_PATH_NATIVE = '/v1/audio/streaming/transcriptions';
export const SERVER_WS_PATH_FUNASR = '/v1/audio/streaming/funasr';

/** localStorage 键名 */
export const STORAGE_KEY = 'bookroom-audio-demo-config';

/** 默认心跳间隔（毫秒） */
export const DEFAULT_HEARTBEAT_INTERVAL_MS = 30000;

/** 默认重连次数 */
export const DEFAULT_RECONNECT_TIMES = 3;

/** 默认重连初始间隔（毫秒） */
export const DEFAULT_RECONNECT_INTERVAL_MS = 1000;

/** 默认重连最大间隔（毫秒） */
export const DEFAULT_RECONNECT_MAX_INTERVAL_MS = 15000;

/** 默认连接超时（毫秒） */
export const DEFAULT_CONNECT_TIMEOUT_MS = 8000;

/** 默认 START 超时（毫秒），首次加载模型可能较慢 */
export const DEFAULT_START_TIMEOUT_MS = 60000;

/** 默认麦克风帧时长（毫秒） */
export const DEFAULT_MIC_FRAME_MS = 100;

/** 默认采样率 */
export const DEFAULT_SAMPLE_RATE = 16000;

/** 热词最大权重 */
export const HOTWORD_MAX_WEIGHT = 100;

/** 热词最小权重 */
export const HOTWORD_MIN_WEIGHT = 1;

/**
 * 从当前页面地址推导服务端 WebSocket URL
 *
 * 规则：
 * - 若页面通过 http://127.0.0.1:5180 访问，则默认指向 ws://127.0.0.1:15231
 * - 若页面通过 http(s)://host:port 访问，则默认指向 ws://host:15231
 * - 兜底返回 ws://127.0.0.1:15231
 */
export function deriveDefaultServerUrl(path: string): string {
  if (typeof location === 'undefined') {
    return `ws://127.0.0.1:${SERVER_DEFAULT_PORT}${path}`;
  }
  const host = location.hostname || '127.0.0.1';
  return `ws://${host}:${SERVER_DEFAULT_PORT}${path}`;
}
