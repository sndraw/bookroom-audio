/**
 * WebSocket 抽象层
 *
 * 在浏览器和 Node.js 之间提供统一接口，避免直接依赖平台 API。
 * 通过工厂函数注入，运行时自动选择实现。
 */

/** WebSocket 抽象接口（事件回调式） */
export interface IWebSocket {
  readonly readyState: number;
  readonly OPEN: number;
  readonly CLOSED: number;

  send(data: string | ArrayBufferLike | ArrayBufferView): void;
  close(code?: number, reason?: string): void;
}

/** WebSocket 事件处理器 */
export interface WebSocketHandlers {
  onOpen?: () => void;
  onMessage?: (data: string | ArrayBuffer | Uint8Array) => void;
  onClose?: (code: number, reason: string) => void;
  onError?: (error: Error) => void;
}

/** WebSocket 工厂函数类型 */
export type WebSocketFactory = (
  url: string,
  handlers: WebSocketHandlers,
  subprotocol?: string,
) => IWebSocket;

/** 检测当前运行环境 */
export function detectRuntime(): 'browser' | 'node' {
  // 浏览器环境：存在 window 和原生 WebSocket
  if (typeof window !== 'undefined') {
    return 'browser';
  }
  // Node.js 环境：检测 globalThis.WebSocket
  if (typeof globalThis !== 'undefined') {
    const g = globalThis as { WebSocket?: unknown };
    if (typeof g.WebSocket !== 'undefined') {
      return 'browser';
    }
  }
  return 'node';
}

/** 浏览器 WebSocket 适配 */
function createBrowserWebSocket(
  url: string,
  handlers: WebSocketHandlers,
  subprotocol?: string,
): IWebSocket {
  const ws = subprotocol
    ? new WebSocket(url, subprotocol)
    : new WebSocket(url);

  ws.binaryType = 'arraybuffer';

  ws.onopen = () => handlers.onOpen?.();
  ws.onmessage = (ev: MessageEvent) => handlers.onMessage?.(ev.data);
  ws.onclose = (ev: CloseEvent) => handlers.onClose?.(ev.code, ev.reason);
  ws.onerror = () => handlers.onError?.(new Error('WebSocket error'));

  return {
    readyState: ws.readyState,
    OPEN: ws.OPEN,
    CLOSED: ws.CLOSED,
    send(data: string | ArrayBufferLike | ArrayBufferView): void {
      ws.send(data as string | ArrayBuffer);
    },
    close(code?: number, reason?: string): void {
      ws.close(code, reason);
    },
  };
}

/**
 * Node.js WebSocket 适配（依赖 ws 包）
 *
 * 使用动态 require 加载 ws，避免浏览器环境打包错误。
 */
function createNodeWebSocket(
  url: string,
  handlers: WebSocketHandlers,
  subprotocol?: string,
): IWebSocket {
  // 动态加载 ws 包
  let WSImpl: new (url: string, protocols?: string) => NodeWSLike;
  try {
    // 用 eval 防止打包工具静态分析 require（避免浏览器环境打包错误）
    // @ts-ignore - 运行时 require，TypeScript 静态检查绕过
    const req = eval('require');
    WSImpl = req('ws');
  } catch {
    throw new Error(
      "Node.js WebSocket requires the 'ws' package. Install it with: npm install ws",
    );
  }

  const ws = subprotocol ? new WSImpl(url, subprotocol) : new WSImpl(url, '');

  ws.on('open', () => handlers.onOpen?.());
  ws.on('message', (data: Uint8Array) => handlers.onMessage?.(data));
  ws.on('close', (code: number, reason: Uint8Array) =>
    handlers.onClose?.(code, reasonToString(reason)),
  );
  ws.on('error', (err: Error) => handlers.onError?.(err));

  return {
    readyState: ws.readyState,
    OPEN: ws.OPEN,
    CLOSED: ws.CLOSED,
    send(data: string | ArrayBufferLike | ArrayBufferView): void {
      ws.send(data);
    },
    close(code?: number, reason?: string): void {
      ws.close(code, reason);
    },
  };
}

/** 将 close reason 转为字符串（兼容 Buffer/Uint8Array） */
function reasonToString(reason: Uint8Array | string): string {
  if (typeof reason === 'string') return reason;
  // Uint8Array → utf-8 string
  try {
    return new TextDecoder('utf-8').decode(reason);
  } catch {
    return '';
  }
}

/** Node.js ws 包的最小接口定义 */
interface NodeWSLike {
  readonly readyState: number;
  readonly OPEN: number;
  readonly CLOSED: number;
  send(data: unknown): void;
  close(code?: number, reason?: string): void;
  on(event: 'open', listener: () => void): void;
  on(event: 'message', listener: (data: Uint8Array) => void): void;
  on(event: 'close', listener: (code: number, reason: Uint8Array) => void): void;
  on(event: 'error', listener: (err: Error) => void): void;
}

/** 默认 WebSocket 工厂（运行时自动检测） */
export const defaultWebSocketFactory: WebSocketFactory = (
  url: string,
  handlers: WebSocketHandlers,
  subprotocol?: string,
): IWebSocket => {
  const runtime = detectRuntime();
  if (runtime === 'browser') {
    return createBrowserWebSocket(url, handlers, subprotocol);
  }
  return createNodeWebSocket(url, handlers, subprotocol);
};
