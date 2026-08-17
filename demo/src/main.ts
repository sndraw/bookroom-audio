/**
 * Demo 主入口
 *
 * 负责：
 * - 初始化 UI 元素引用
 * - 加载/保存配置
 * - 绑定按钮事件
 * - 协调 ASRController 与 UI
 */

import { ClientState, FinalMessage } from '@bookroom/audio-sdk';
import { ASRController } from './asr-controller';
import {
  DEFAULT_MIC_FRAME_MS,
  DEFAULT_SAMPLE_RATE,
  deriveDefaultServerUrl,
  SERVER_WS_PATH_FUNASR,
  SERVER_WS_PATH_NATIVE,
} from './config';
import {
  applyPersistedConfig,
  loadConfig,
  readClientOptions,
  readSessionConfig,
  saveConfig,
} from './persistence';
import {
  appendFinalUI,
  appendLog,
  clearResultsUI,
  getUIElements,
  logStarted,
  UIElements,
  updateButtonsUI,
  updatePartialUI,
  updateRttUI,
  updateStateUI,
} from './ui';

/** 主入口 */
async function main(): Promise<void> {
  const els = getUIElements();

  // 初始化默认 URL（在加载持久化配置之前，作为兜底）
  if (!els.url.value) {
    els.url.value = deriveDefaultServerUrl(SERVER_WS_PATH_NATIVE);
  }

  // 加载持久化配置
  const cfg = loadConfig();
  if (cfg) {
    applyPersistedConfig(els, cfg);
  }

  // 同步初始 UI 状态
  syncModeUI(els);
  updateStateUI(els, { state: 'idle' });
  updateButtonsUI(els, 'idle');

  // 创建控制器引用（单例，对应一次"开始-停止"周期）
  let controller: ASRController | null = null;

  /** 安全重置控制器 */
  const resetController = (): void => {
    if (controller !== null) {
      controller.close();
      controller = null;
    }
    updateButtonsUI(els, 'idle');
    updateStateUI(els, { state: 'idle' });
  };

  // 绑定事件
  bindEvents(els, () => controller, (c) => { controller = c; }, resetController);

  appendLog(els, 'info',
    `Demo 已就绪。${ASRController.isSupported()
      ? '浏览器支持麦克风采集'
      : '当前环境不支持麦克风（需 HTTPS 或 localhost）'}`);
}

/** 同步 mode 变化时 UI 的联动 */
function syncModeUI(els: UIElements): void {
  const isNative = els.mode.value === 'native';
  els.engine.disabled = !isNative;
  els.chunkSize.disabled = !isNative;
  els.btnPause.disabled = !isNative || els.btnPause.disabled;
  els.btnResume.disabled = !isNative || els.btnResume.disabled;

  // 切换 mode 时同步 URL 路径
  const currentUrl = els.url.value;
  const isInFunasrPath = currentUrl.includes(SERVER_WS_PATH_FUNASR);
  const isInNativePath = currentUrl.includes(SERVER_WS_PATH_NATIVE);

  if (isNative && isInFunasrPath) {
    els.url.value = currentUrl.replace(
      SERVER_WS_PATH_FUNASR,
      SERVER_WS_PATH_NATIVE,
    );
  } else if (!isNative && isInNativePath) {
    els.url.value = currentUrl.replace(
      SERVER_WS_PATH_NATIVE,
      SERVER_WS_PATH_FUNASR,
    );
  }
}

/** 绑定所有事件 */
function bindEvents(
  els: UIElements,
  getController: () => ASRController | null,
  setController: (c: ASRController | null) => void,
  resetController: () => void,
): void {
  // mode 切换：联动 engine/chunkSize/URL 路径
  els.mode.addEventListener('change', () => {
    syncModeUI(els);
    saveConfig(els);
  });

  // 任意配置变更：自动持久化
  [els.url, els.apiKey, els.engine, els.chunkSize, els.silence, els.hotwords]
    .forEach((el) => {
      el.addEventListener('change', () => saveConfig(els));
    });

  // 开始识别
  els.btnStart.addEventListener('click', async () => {
    if (getController() !== null) {
      return;
    }
    await onStart(els, setController, resetController);
  });

  // 停止
  els.btnStop.addEventListener('click', async () => {
    const controller = getController();
    if (controller === null) {
      return;
    }
    appendLog(els, 'info', '用户点击停止，发送 STOP...');
    els.btnStop.disabled = true;
    try {
      await controller.stop();
    } catch (err) {
      appendLog(els, 'error', `停止失败：${(err as Error).message}`);
    }
    // close 在 onClosed 回调中触发，这里不立即清理 controller
  });

  // 暂停
  els.btnPause.addEventListener('click', async () => {
    const controller = getController();
    if (controller === null) {
      return;
    }
    try {
      await controller.pause();
      appendLog(els, 'info', '已发送 PAUSE');
    } catch (err) {
      appendLog(els, 'error', `暂停失败：${(err as Error).message}`);
    }
  });

  // 恢复
  els.btnResume.addEventListener('click', async () => {
    const controller = getController();
    if (controller === null) {
      return;
    }
    try {
      await controller.resume();
      appendLog(els, 'info', '已发送 RESUME');
    } catch (err) {
      appendLog(els, 'error', `恢复失败：${(err as Error).message}`);
    }
  });

  // 清空
  els.btnClear.addEventListener('click', () => {
    clearResultsUI(els);
  });
}

/** 处理开始识别 */
async function onStart(
  els: UIElements,
  setController: (c: ASRController | null) => void,
  resetController: () => void,
): Promise<void> {
  try {
    const { mode, config: sessionConfig } = readSessionConfig(els);
    const clientOptions = readClientOptions(els, mode);

    appendLog(els, 'info',
      `连接 ${clientOptions.url}（mode=${mode}）`);

    // 创建控制器
    const controller = new ASRController({
      onStateChange: (state) => {
        const cs = state as ClientState;
        updateStateUI(els, { state: cs });
        updateButtonsUI(els, cs);
        appendLog(els, 'state', `状态变更：${state}`);
      },
      onStarted: (engine, sessionId) => {
        updateStateUI(els, { state: 'started', engine, sessionId });
        logStarted(els, {
          type: 'started',
          session_id: sessionId,
          engine,
          config: {},
        });
      },
      onPartial: (text) => {
        updatePartialUI(els, text);
        if (text) {
          appendLog(els, 'partial', `PARTIAL: ${text}`);
        }
      },
      onFinal: (text, msg) => {
        const finalMsg = msg as FinalMessage;
        appendFinalUI(els, finalMsg);
        appendLog(els, 'final', `FINAL #${finalMsg.sentence_id}: ${text}`);
      },
      onError: (code, message) => {
        appendLog(els, 'error', `ERROR ${code}: ${message}`);
      },
      onClosed: (reason) => {
        appendLog(els, 'info', `连接已关闭：${reason}`);
        // 清理控制器
        resetController();
      },
      onPong: (rttMs) => {
        updateRttUI(els, rttMs);
        appendLog(els, 'info', `PONG RTT=${rttMs}ms`);
      },
      onReconnectAttempt: (attempt, delayMs) => {
        appendLog(els, 'reconnect',
          `重连第 ${attempt} 次，${delayMs}ms 后重试`);
      },
      onAudioChunk: (bytes) => {
        appendLog(els, 'audio', `音频帧 ${bytes}B`);
      },
    });

    setController(controller);

    await controller.start({
      url: clientOptions.url!,
      apiKey: clientOptions.apiKey,
      mode,
      sessionConfig,
      micOptions: {
        sampleRate: DEFAULT_SAMPLE_RATE,
        channelCount: 1,
        frameMs: DEFAULT_MIC_FRAME_MS,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    saveConfig(els);
  } catch (err) {
    appendLog(els, 'error', `启动失败：${(err as Error).message}`);
    resetController();
  }
}

// 启动
main().catch((err) => {
  console.error('[Demo] init failed:', err);
});
