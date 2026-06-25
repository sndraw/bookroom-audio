/**
 * bookroom-audio 流式 ASR 客户端 SDK 入口
 *
 * 同时支持浏览器和 Node.js 环境。
 * - 浏览器：内置麦克风采集（AudioWorklet）
 * - Node.js：需自行实现音频采集后调用 sendAudio
 */

export { BookRoomASRClient, ASRClientError } from './client';
export {
  IWebSocket,
  WebSocketFactory,
  WebSocketHandlers,
  defaultWebSocketFactory,
  detectRuntime,
} from './websocket';

export {
  MicCapturer,
  startMicToClient,
  micOptionsFromConfig,
  isMicSupported,
  isAudioFormatSupported,
  PCMChunkCallback,
  MicCapturerOptions,
} from './mic';

export * from './types';
