/**
 * Demo 配置解析与持久化
 *
 * - 从 UI 读取用户配置
 * - 解析热词文本为 Record<string, number>
 * - 通过 localStorage 持久化最近一次配置
 */

import {
  StreamingASREngine,
  StreamingSessionConfig,
  ClientOptions,
} from '@bookroom/audio-sdk';
import {
  HOTWORD_MAX_WEIGHT,
  HOTWORD_MIN_WEIGHT,
  STORAGE_KEY,
} from './config';
import { UIElements } from './ui';

/** 协议模式 */
export type ProtocolMode = 'native' | 'funasr';

/** 解析 chunk_size 字符串为元组 */
export function parseChunkSize(
  raw: string,
): [number, number, number] {
  const parts = raw.split(',').map((s) => parseInt(s.trim(), 10));
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n) || n <= 0)) {
    return [5, 10, 5];
  }
  return [parts[0]!, parts[1]!, parts[2]!];
}

/** 解析热词文本为权重映射 */
export function parseHotwords(
  raw: string,
): Record<string, number> | undefined {
  if (!raw.trim()) {
    return undefined;
  }

  const result: Record<string, number> = {};
  const lines = raw.split(/\r?\n/);

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }

    // 支持 "词:权重" 或 "词=权重" 或 "词 权重"
    const match = trimmed.match(/^(.+?)[:\s=]+(\d+)$/);
    if (match) {
      const word = match[1]!.trim();
      const weight = Math.min(
        HOTWORD_MAX_WEIGHT,
        Math.max(HOTWORD_MIN_WEIGHT, parseInt(match[2]!, 10)),
      );
      if (word) {
        result[word] = weight;
      }
    } else {
      // 无权重则默认 10
      result[trimmed] = 10;
    }
  }

  return Object.keys(result).length > 0 ? result : undefined;
}

/** 从 UI 读取完整会话配置 */
export function readSessionConfig(els: UIElements): {
  mode: ProtocolMode;
  config: StreamingSessionConfig;
} {
  const mode = els.mode.value as ProtocolMode;
  const chunkSize = parseChunkSize(els.chunkSize.value);
  const hotwords = parseHotwords(els.hotwords.value);
  const silence = parseInt(els.silence.value, 10);

  const config: StreamingSessionConfig = {
    audio_format: 'pcm',
    sample_rate: 16000,
    enable_punctuation: true,
    enable_vad: true,
    enable_itn: true,
    chunk_size: chunkSize,
    max_sentence_silence_ms: silence,
    ...(hotwords !== undefined ? { hotwords } : {}),
  };

  // native 模式才设置 engine；funasr 模式由服务端默认
  if (mode === 'native') {
    config.engine = els.engine.value as StreamingASREngine;
  }

  return { mode, config };
}

/** 从 UI 读取客户端连接选项 */
export function readClientOptions(
  els: UIElements,
  mode: ProtocolMode,
): ClientOptions {
  return {
    url: els.url.value.trim(),
    apiKey: els.apiKey.value.trim() || undefined,
    mode,
    reconnect: 3,
    reconnectInterval: 1000,
    reconnectMaxInterval: 15000,
    connectTimeout: 8000,
    startTimeout: 60000,
    heartbeatInterval: 30000,
  };
}

/** 持久化配置参数 */
export interface PersistedConfig {
  url: string;
  apiKey: string;
  mode: ProtocolMode;
  engine: string;
  chunkSize: string;
  silence: string;
  hotwords: string;
}

/** 从 UI 收集可持久化配置 */
export function collectPersistedConfig(els: UIElements): PersistedConfig {
  return {
    url: els.url.value,
    apiKey: els.apiKey.value,
    mode: els.mode.value as ProtocolMode,
    engine: els.engine.value,
    chunkSize: els.chunkSize.value,
    silence: els.silence.value,
    hotwords: els.hotwords.value,
  };
}

/** 应用持久化配置到 UI */
export function applyPersistedConfig(
  els: UIElements,
  cfg: PersistedConfig,
): void {
  els.url.value = cfg.url;
  els.apiKey.value = cfg.apiKey;
  els.mode.value = cfg.mode;
  els.engine.value = cfg.engine;
  els.chunkSize.value = cfg.chunkSize;
  els.silence.value = cfg.silence;
  els.hotwords.value = cfg.hotwords;
}

/** 保存配置到 localStorage */
export function saveConfig(els: UIElements): void {
  try {
    const cfg = collectPersistedConfig(els);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
  } catch {
    // 忽略 localStorage 不可用（隐私模式等）
  }
}

/** 从 localStorage 加载配置 */
export function loadConfig(): PersistedConfig | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw) as PersistedConfig;
  } catch {
    return null;
  }
}
