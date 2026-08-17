# bookroom-audio 对接指南

本指南介绍如何让外部项目对接 bookroom-audio 的实时语音识别（ASR）服务。

## 概览

bookroom-audio 提供两种对接方式：

| 方式 | 协议端点 | 适用场景 |
|------|---------|---------|
| **原生协议** | `ws://<host>:<port>/v1/audio/streaming/transcriptions` | 使用 bookroom-audio SDK 或自定义客户端，功能最完整 |
| **FunASR 兼容协议** | `ws://<host>:<port>/v1/audio/streaming/funasr` | 已有 FunASR 官方客户端 SDK 的项目，零改动对接 |

两者共享同一套引擎（FunASR-Local / SenseVoice-Local / FunASR-Server），仅消息格式不同。

## 鉴权

所有端点均通过 Query 参数 `token` 鉴权：

```
ws://host:port/v1/audio/streaming/transcriptions?token=YOUR_API_KEY
```

`YOUR_API_KEY` 来自服务端 `.env` 中的 `API_KEY` 配置。未配置鉴权时可省略。

## REST 接口

### 查询可用引擎

```
GET /v1/audio/streaming/engines
```

返回当前服务端可用的流式 ASR 引擎列表，用于客户端选择。

## 引擎选择

| 引擎 | 模式 | 特点 |
|------|------|------|
| `funasr-local` | 流式 | Paraformer 流式模型，实时输出 PARTIAL + 句末 FINAL |
| `sensevoice-local` | 伪流式 | SenseVoice + VAD，整句识别后输出 |
| `funasr-server` | 对接外部 | 对接外部 FunASR Server，需配置 `STREAMING_FUNASR_SERVER_URL` |

### 2pass 纠错机制（funasr-local 默认启用）

为解决流式模型在同音字、复杂长句上易出现的"听写错误"，`funasr-local` 引擎采用 **2pass 识别模式**：

1. **PARTIAL 阶段（流式实时）**：使用 `paraformer-zh-streaming` 流式模型逐 chunk 推理，输出"累积整句"作为 PARTIAL，让用户即时看到结果。流式模型不挂载标点模型，避免 PARTIAL 阶段错误加标点导致后续纠正困难。
2. **FINAL 阶段（离线精确纠错）**：会话 STOP 时，用独立的 `paraformer-zh`（离线精确模型）对整段会话音频重新识别，纠正流式阶段可能出现的同音字、近音字错误；再对纠错后的整句文本应用 `ct-punc` 标点恢复模型，输出带标点的 FINAL。
3. **失败回退**：若离线模型加载或推理失败，自动回退到流式累积文本 + 标点恢复，保证可用性。

效果示例（PARTIAL 逐步增长 → FINAL 纠错 + 标点）：
```
PARTIAL: '你' → '你好' → '你好这是一个' → ... → '你好这是一个真实的中文语音测试今天天气很好我们一起去公园散步吧'
FINAL:   '你好，这是一个真实的中文语音测试。今天天气很好，我们一起去公园散步吧。'
```

相关配置项：
- `STREAMING_ASR_MODEL`：流式模型（默认 `paraformer-zh-streaming`）
- `STREAMING_OFFLINE_MODEL`：2pass 离线精确模型（默认 `paraformer-zh`）
- `STREAMING_PUNC_MODEL`：标点恢复模型（默认 `ct-punc`）

---

## 一、原生协议

### 消息格式（JSON）

所有消息均以 UTF-8 文本帧发送，`type` 字段标识消息类型。

#### 客户端 → 服务端

**1. START - 启动会话**

```json
{
  "type": "start",
  "config": {
    "engine": "funasr-local",
    "language": "zh",
    "audio_format": "pcm",
    "sample_rate": 16000,
    "enable_punctuation": true,
    "enable_vad": true,
    "enable_itn": true,
    "enable_speaker_diarization": false,
    "enable_emotion": false,
    "hotwords": {"阿里巴巴": 20},
    "chunk_size": [5, 10, 5],
    "max_sentence_silence_ms": 1300
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `engine` | string | 引擎名，可选。未填则使用服务端默认值 |
| `language` | string | 语言代码，默认 `zh` |
| `audio_format` | string | 音频格式：`pcm` / `wav` / `mp3` |
| `sample_rate` | int | 采样率，默认 16000 |
| `enable_punctuation` | bool | 是否启用标点恢复 |
| `enable_vad` | bool | 是否启用 VAD 自动断句 |
| `enable_itn` | bool | 是否启用逆文本归一化（数字/日期等） |
| `enable_speaker_diarization` | bool | 是否启用说话人分离 |
| `enable_emotion` | bool | 是否启用情感识别 |
| `hotwords` | object | 热词表，键为热词，值为权重 |
| `chunk_size` | int[3] | 流式分块配置 |
| `max_sentence_silence_ms` | int | VAD 静音断句阈值（毫秒） |

**2. 二进制音频帧**

START 后，客户端通过 WebSocket 二进制帧持续发送音频数据：
- 格式必须与 `audio_format` 一致
- 推荐每帧 100-600ms 音频（16kHz PCM = 3200-19200 字节）
- 发送 PCM 时，服务端直接转发；发送 WAV/MP3 时，服务端自动解码

**3. STOP - 结束会话**

```json
{"type": "stop"}
```

发送后服务端会推送剩余的 FINAL 结果，再发送 CLOSED 消息并关闭连接。

**4. PING - 心跳保活**

```json
{"type": "ping", "timestamp_ms": 1723800000000}
```

建议每 30 秒发送一次。服务端立即回 PONG（含 `client_time_ms` 回显，可用于计算 RTT）。**服务端超过 90 秒未收到任何消息（含音频帧）会主动断开**，长连接务必启用心跳。

**5. PAUSE / RESUME - 暂停 / 恢复**

```json
{"type": "pause"}
{"type": "resume"}
```

- `PAUSE`：暂停音频处理。暂停期间服务端**丢弃**收到的音频帧，不送入引擎。
- `RESUME`：恢复处理。
- 服务端分别回 `paused` / `resumed` 消息确认，重复发送同类型请求会被忽略（幂等）。
- 场景：用户点击「静音/暂停」时，暂停期间的服务端音频不做识别，恢复后继续。

#### 服务端 → 客户端

**1. STARTED - 会话已启动**

```json
{
  "type": "started",
  "session_id": "uuid-xxxx",
  "engine": "funasr-local",
  "config": { /* 实际生效的配置 */ }
}
```

**2. PARTIAL - 实时中间结果**

> **语义说明（替换式）**：每条 PARTIAL 的 `text` 都是"**到目前为止的整句识别结果**"，后到的会覆盖前一条。客户端直接用最新 PARTIAL 的 `text` 替换当前显示即可，无需自己拼接增量。

```json
{
  "type": "partial",
  "session_id": "uuid-xxxx",
  "text": "你好这是一个真实的",
  "is_final": false,
  "sentence_id": 0,
  "timestamp_ms": 4200
}
```

PARTIAL 序列示例（`text` 不断增长，非单 chunk 增量）：
```
'你' → '你好' → '你好这是一个' → '你好这是一个真实的中' → ...
```

**3. FINAL - 句末最终结果**

```json
{
  "type": "final",
  "session_id": "uuid-xxxx",
  "text": "你好，这是一个测试。",
  "sentence_id": 0,
  "start_ms": 0,
  "end_ms": 1800,
  "speaker": null,
  "emotion": null,
  "words": [
    {"text": "你好", "start_ms": 0, "end_ms": 500},
    {"text": "这是一个测试", "start_ms": 600, "end_ms": 1800}
  ]
}
```

**4. ERROR - 错误消息**

```json
{
  "type": "error",
  "session_id": "uuid-xxxx",
  "code": "audio_decode_failed",
  "message": "Decoding failed: ..."
}
```

错误码包括：`auth_failed` / `invalid_config` / `engine_unavailable` / `audio_decode_failed` / `session_not_found` / `internal_error` 等。

**6. PONG - 心跳响应**

```json
{
  "type": "pong",
  "session_id": "uuid-xxxx",
  "server_time_ms": 1723800000000,
  "client_time_ms": 1723800000000
}
```

`client_time_ms` 为回显客户端 PING 中的时间戳；客户端可用 `RTT ≈ now - client_time_ms` 估算网络延迟。

**7. PAUSED / RESUMED - 暂停 / 恢复确认**

```json
{
  "type": "paused",
  "session_id": "uuid-xxxx",
  "paused_at_ms": 4200
}
{
  "type": "resumed",
  "session_id": "uuid-xxxx",
  "resumed_at_ms": 8700
}
```

`paused_at_ms` / `resumed_at_ms` 为操作发生时已累积的音频时长（毫秒）。

**8. CLOSED - 连接关闭**

```json
{
  "type": "closed",
  "session_id": "uuid-xxxx",
  "reason": "normal"
}
```

`reason` 取值：`normal`（正常关闭）/ `client_disconnected` / `server_shutdown` / `error` / `idle_timeout`。

---

## 二、FunASR 兼容协议

与 FunASR 官方 `serve_realtime_ws.py` 协议兼容，使用 FunASR 官方客户端 SDK（Python/Java/JS/C++）的项目可直接对接，无需修改代码。

### 消息格式

#### 客户端 → 服务端

**1. 初始化 JSON（连接后立即发送）**

```json
{
  "mode": "2pass",
  "chunk_size": [5, 10, 5],
  "wav_name": "microphone",
  "is_speaking": true,
  "itn": true,
  "audio_fs": 16000,
  "wav_format": "pcm",
  "hotwords": "{\"阿里巴巴\":20}"
}
```

| 字段 | 说明 |
|------|------|
| `mode` | `online`（纯流式）/ `offline`（整句）/ `2pass`（流式 + 句末修正，推荐） |
| `chunk_size` | 流式分块配置 |
| `wav_name` | 音频源标识，响应中会原样回显 |
| `is_speaking` | 必须为 `true` |
| `itn` | 是否启用逆文本归一化 |
| `audio_fs` | 采样率 |
| `wav_format` | `pcm` / `wav` / `mp3` |
| `hotwords` | JSON 字符串形式的热词表 |

**2. 二进制音频帧**

发送 PCM 二进制数据，推荐 600ms 一帧。

**3. 结束信号**

```json
{"is_speaking": false}
```

#### 服务端 → 客户端

**1. PARTIAL（2pass-online）**

> **语义说明（替换式）**：每条 PARTIAL 的 `text` 都是"**到目前为止的整句识别结果**"，后到的会覆盖前一条。客户端直接用最新 `text` 替换当前显示即可，无需自己拼接增量。

```json
{
  "mode": "2pass-online",
  "wav_name": "microphone",
  "text": "你好这是一个真实的",
  "is_final": false
}
```

**2. FINAL（2pass-offline）**

```json
{
  "mode": "2pass-offline",
  "wav_name": "microphone",
  "text": "你好，这是一个测试。",
  "is_final": true,
  "timestamp": "[[0,500],[600,1800]]"
}
```

> 标点说明：PARTIAL 返回累积整句但不含标点（保持实时性）；FINAL 为整句经标点恢复模型（ct-punc）处理后的完整文本，包含逗号、句号等标点。

**3. 错误消息**

```json
{
  "mode": "",
  "wav_name": "microphone",
  "text": "[error:audio_decode_failed] Decoding failed: ...",
  "is_final": true,
  "error": true,
  "error_code": "audio_decode_failed"
}
```

### 模式映射

| FunASR `mode` | bookroom-audio 引擎 |
|---------------|---------------------|
| `online` | `funasr-local`（纯流式 Paraformer） |
| `2pass` | `funasr-local`（流式 + 句末修正） |
| `offline` | `sensevoice-local`（整句识别） |

---

## 三、客户端 SDK

为简化对接，提供 TypeScript/JavaScript SDK，同时支持浏览器和 Node.js。

### 位置

```
sdk/typescript/
├── src/
│   ├── client.ts       # 核心客户端
│   ├── mic.ts          # 浏览器麦克风采集
│   ├── websocket.ts    # 跨平台 WebSocket
│   ├── types.ts        # 类型定义
│   └── index.ts        # 入口
├── examples/
│   ├── browser_mic.html  # 浏览器示例
│   └── node_file_stream.js  # Node.js 示例
└── package.json
```

### 安装

```bash
# 在 SDK 目录下编译
cd sdk/typescript
npm install
npm run build
```

### 浏览器使用

```typescript
import { BookRoomASRClient, MicCapturer } from 'bookroom-audio-sdk';

const client = new BookRoomASRClient(
  {
    url: 'ws://127.0.0.1:15231/v1/audio/streaming/transcriptions',
    apiKey: 'YOUR_KEY',
    mode: 'native', // 或 'funasr'
    // 增强能力（均可选）：
    heartbeatInterval: 30000, // 心跳间隔 ms，0 关闭（默认 30000）
    reconnect: 3,             // 断线自动重连次数，0 关闭（默认 0）
    reconnectInterval: 1000,  // 重连初始延迟 ms（默认 1000，指数退避）
    reconnectMaxInterval: 30000, // 重连最大延迟 ms（默认 30000）
  },
  {
    onStarted: (msg) => console.log('Session:', msg.session_id),
    onPartial: (text) => console.log('Partial:', text),
    onFinal: (text) => console.log('Final:', text),
    onPong: (msg, rttMs) => console.log('RTT:', rttMs, 'ms'),
    onPaused: (msg) => console.log('Paused at', msg.paused_at_ms),
    onResumed: (msg) => console.log('Resumed at', msg.resumed_at_ms),
    onReconnectAttempt: (attempt, delayMs) =>
      console.log(`Reconnect ${attempt} in ${delayMs}ms`),
    onClosed: (msg) => console.log('Closed:', msg.reason),
  },
);

await client.connect();
await client.start({
  audio_format: 'pcm',
  sample_rate: 16000,
});

// 暂停 / 恢复（仅 native 模式，收到 paused/resumed 后状态切换）
await client.pause();   // 暂停期间服务端丢弃音频
await client.resume();  // 恢复

// 启动麦克风
const mic = new MicCapturer(
  (chunk) => client.sendAudio(chunk),
  { sampleRate: 16000, frameMs: 100 },
);
await mic.start();

// 停止
await client.stop();
mic.stop();
// 主动关闭（不触发重连）
client.close();
```

> **重连与恢复**：启用 `reconnect > 0` 后，异常断线会自动指数退避重连（带 ±25% 抖动），重连成功后自动重发 START 恢复会话；用户主动 `close()` 不会重连。

### Node.js 使用

```javascript
const fs = require('fs');
const { BookRoomASRClient } = require('bookroom-audio-sdk');

const client = new BookRoomASRClient({
  url: 'ws://127.0.0.1:15231/v1/audio/streaming/transcriptions',
  apiKey: process.env.BOOKROOM_AUDIO_KEY,
});

await client.connect();
await client.start({ audio_format: 'pcm', sample_rate: 16000 });

// 从文件流式发送
const stream = fs.createReadStream('audio.wav', { highWaterMark: 19200 });
stream.on('data', (chunk) => client.sendAudio(chunk.buffer));
stream.on('end', async () => {
  await client.stop();
  client.close();
});
```

完整示例见：
- `sdk/typescript/examples/browser_mic.html`
- `sdk/typescript/examples/node_file_stream.js`

---

## 四、测试

测试脚本位于 `tests/streaming_asr/`，提供统一入口，按模块拆分：

### 环境变量配置

```bash
export SERVER_HOST=127.0.0.1
export SERVER_PORT=15231
export API_KEY=test_api_key
export TEST_AUDIO_WAV=tests/real_chinese_audio.wav
export TEST_TIMEOUT=120
```

### 统一测试入口（推荐）

```bash
# 运行所有模块
python -m tests.streaming_asr

# 只测原生协议
python -m tests.streaming_asr --module native

# 只测 FunASR 兼容
python -m tests.streaming_asr --module funasr_compat
```

### 单独运行模块

```bash
# 原生协议端点
python -m tests.streaming_asr.test_native

# FunASR 兼容端点
python -m tests.streaming_asr.test_funasr_compat
```

### 单元测试（无需服务器与模型）

新增功能的纯单元测试，不依赖真实服务器与模型，可在开发环境直接运行：

```bash
# 后端：心跳 / 暂停恢复 / 心跳超时 / 字级时间戳 / SenseVoice 去重
python -m unittest tests.streaming_asr.test_protocol_features -v

# SDK：心跳 / pause-resume / 指数退避重连 / 主动关闭不重连
cd sdk/typescript
npm run build && npm test
```

### 测试验证内容

测试脚本自动验证：
- 连接建立
- 消息格式符合协议规范
- 必需字段齐全
- PARTIAL（替换式整句）+ FINAL（整句 + 标点）正确返回
- 标点恢复模型生效（ct-punc）

### 测试结果示例

```
[PARTIAL] '你'
[PARTIAL] '你好'
[PARTIAL] '你好这是一个'
[PARTIAL] '你好这是一个真实的中'
...
[FINAL] sentence#0 text='你好，这是一个真实的中文语音测试。今天天气很好，我们一起去公园散步吧。'
```

---

## 五、典型对接场景

### 场景 1：bookroom-chat 集成实时语音输入

bookroom-chat 作为 Agent 对话项目，可以让用户通过麦克风实时输入文本：

1. 在 bookroom-chat 前端引入 bookroom-audio SDK
2. 用户点击「语音输入」时，建立 WebSocket 连接
3. 采集麦克风音频，流式发送到 bookroom-audio
4. 收到 FINAL 结果后，填充到聊天输入框
5. 用户点击「发送」，将文本提交给 Agent

### 场景 2：电话客服转写

1. 通过 SIP/PSTN 网关采集电话音频
2. 转换为 16kHz PCM 流
3. 通过 WebSocket 发送到 bookroom-audio
4. 收到实时转写结果，存入对话记录

### 场景 3：会议记录

1. 通过浏览器 getUserMedia 采集会议室音频
2. 启用说话人分离
3. 按 FINAL 结果分句存储，标注说话人
4. 会议结束后生成完整纪要

---

## 六、配置参考

服务端通过 `.env` 配置：

```bash
# 服务端地址
HOST=0.0.0.0
PORT=15231
API_KEY=your_api_key

# 流式 ASR
STREAMING_ASR_ENGINE=funasr-local
STREAMING_ASR_MODEL=paraformer-zh-streaming
STREAMING_OFFLINE_MODEL=paraformer-zh
STREAMING_VAD_MODEL=fsmn-vad
STREAMING_PUNC_MODEL=ct-punc
STREAMING_CHUNK_MS=600

# 模型缓存
CACHE_DIR=./docker-deploy/.cache
```

详细配置见 `docs/CONFIGURATION.md`。
