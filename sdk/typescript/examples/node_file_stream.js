/**
 * Node.js 示例：流式发送音频文件到 bookroom-audio
 *
 * 使用方式：
 *   node examples/node_file_stream.js
 *
 * 依赖：npm install ws
 * （SDK 会自动通过动态 require 加载 ws 包）
 *
 * 环境变量：
 *   BOOKROOM_AUDIO_URL  - WebSocket URL
 *   BOOKROOM_AUDIO_KEY  - API Key（可选）
 *   AUDIO_FILE          - 音频文件路径
 *   USE_FUNASR_MODE=1   - 使用 FunASR 兼容协议
 */

const fs = require('fs');
const path = require('path');
const { BookRoomASRClient, ASRClientError } = require('../src');

// ==================== 配置（读取环境变量） ====================

const SERVER_URL = process.env.BOOKROOM_AUDIO_URL
  || 'ws://127.0.0.1:15231/v1/audio/streaming/transcriptions';
const API_KEY = process.env.BOOKROOM_AUDIO_KEY;
const AUDIO_FILE = process.env.AUDIO_FILE
  || path.resolve(__dirname, '../../../tests/real_chinese_audio.wav');
const USE_FUNASR_MODE = process.env.USE_FUNASR_MODE === '1';

// 流式发送参数（模拟实时麦克风）
const CHUNK_SIZE_BYTES = 16000 * 2 * 0.6; // 600ms PCM = 19200 bytes
const SEND_INTERVAL_MS = 100;

// ==================== 主流程 ====================

async function main() {
  console.log('=== bookroom-audio Node.js 示例 ===');
  console.log(`Server:  ${SERVER_URL}`);
  console.log(`Mode:    ${USE_FUNASR_MODE ? 'FunASR 兼容' : 'native'}`);
  console.log(`Audio:   ${AUDIO_FILE}`);
  console.log('');

  if (!fs.existsSync(AUDIO_FILE)) {
    console.error(`Audio file not found: ${AUDIO_FILE}`);
    process.exit(1);
  }

  const client = new BookRoomASRClient(
    {
      url: SERVER_URL,
      apiKey: API_KEY,
      mode: USE_FUNASR_MODE ? 'funasr' : 'native',
      connectTimeout: 5000,
      startTimeout: 30000,
    },
    {
      onConnected: () => console.log('[连接] WebSocket 已连接'),
      onStarted: (msg) => console.log(
        `[启动] session=${msg.session_id} engine=${msg.engine}`,
      ),
      onPartial: (text, msg) => console.log(
        `[实时] sentence#${msg.sentence_id}: ${text}`,
      ),
      onFinal: (text, msg) => console.log(
        `[句末] sentence#${msg.sentence_id} [${msg.start_ms}ms-${msg.end_ms}ms]: ${text}`,
      ),
      onError: (err) => console.error(`[错误] ${err.code}: ${err.message}`),
      onClosed: (msg) => console.log(`[关闭] ${msg.reason}`),
    },
  );

  let resolveOnFinal;
  const finalPromise = new Promise((resolve) => {
    resolveOnFinal = resolve;
  });

  // 在 onFinal 上叠加 resolve
  client.setCallbacks({
    onConnected: () => console.log('[连接] WebSocket 已连接'),
    onStarted: (msg) => console.log(
      `[启动] session=${msg.session_id} engine=${msg.engine}`,
    ),
    onPartial: (text, msg) => console.log(
      `[实时] sentence#${msg.sentence_id}: ${text}`,
    ),
    onFinal: (text, msg) => {
      console.log(
        `[句末] sentence#${msg.sentence_id} [${msg.start_ms}ms-${msg.end_ms}ms]: ${text}`,
      );
      resolveOnFinal();
    },
    onError: (err) => {
      console.error(`[错误] ${err.code}: ${err.message}`);
      resolveOnFinal();
    },
    onClosed: (msg) => {
      console.log(`[关闭] ${msg.reason}`);
      resolveOnFinal();
    },
  });

  try {
    // 1. 建立连接
    await client.connect();

    // 2. 启动会话
    await client.start({
      engine: USE_FUNASR_MODE ? undefined : 'funasr-local',
      audio_format: 'wav',  // 服务端会解码 WAV
      sample_rate: 16000,
      enable_punctuation: true,
      enable_vad: true,
      enable_itn: true,
    });

    // 3. 流式发送音频文件
    console.log('\n[发送] 开始流式发送音频...');
    await streamFileToClient(client, AUDIO_FILE);
    console.log('[发送] 音频文件发送完成');

    // 4. 停止会话
    console.log('\n[停止] 发送 STOP...');
    await client.stop();

    // 等待服务端 FINAL 结果（最多 10 秒）
    await Promise.race([
      finalPromise,
      new Promise((resolve) => setTimeout(resolve, 10000)),
    ]);

    console.log('\n=== 完成 ===');
  } catch (err) {
    if (err instanceof ASRClientError) {
      console.error(`ASR Error [${err.code}]: ${err.message}`);
    } else {
      console.error('Unexpected error:', err);
    }
    process.exit(1);
  } finally {
    client.close();
  }
}

/**
 * 流式发送音频文件到客户端
 * 控制发送速率以模拟实时麦克风采集
 */
function streamFileToClient(client, filePath) {
  return new Promise((resolve, reject) => {
    const stream = fs.createReadStream(filePath, {
      highWaterMark: CHUNK_SIZE_BYTES,
    });

    let totalSent = 0;

    const sendNext = () => {
      const chunk = stream.read(CHUNK_SIZE_BYTES);
      if (chunk === null) return;

      totalSent += chunk.length;
      client.sendAudio(chunk.buffer.slice(
        chunk.byteOffset,
        chunk.byteOffset + chunk.byteLength,
      ));

      setTimeout(sendNext, SEND_INTERVAL_MS);
    };

    stream.on('readable', sendNext);
    stream.on('end', () => {
      console.log(`[发送] 文件读取完成，已发送 ${totalSent} 字节`);
      resolve();
    });
    stream.on('error', reject);
  });
}

main().catch((err) => {
  console.error('Fatal:', err);
  process.exit(1);
});
