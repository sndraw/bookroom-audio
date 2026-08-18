# 模型下载和缓存说明

## 统一缓存目录

所有模型（TTS 和 ASR）现在统一存储在 `./docker-deploy/.cache` 目录下，便于管理和迁移。开发环境与 Docker 部署使用同一缓存目录，方便模型迁移和共享。

## 模型下载源配置

推荐使用阿里 ModelScope 作为模型下载源（国内访问更稳定）：

```bash
# 设置环境变量
export HF_ENDPOINT=https://www.modelscope.cn

# 或在 .env 文件中配置
HF_ENDPOINT=https://www.modelscope.cn
```

## CosyVoice 2 模型下载（Apache 2.0，可商用，本地离线）

> **推荐商用 TTS 引擎**：中文韵律开源第一梯队、流式合成、3 秒零样本音色克隆。替代 ChatTTS（不可商用）与 edge-tts（在线依赖）。

### 1. 安装 cosyvoice 包（PyPI 无官方包，需从 git 安装）

```bash
pip install git+https://github.com/FunAudioLLM/CosyVoice.git
# 国内加速可用镜像：
# pip install git+https://gitcode.com/gh_mirrors/cos/CosyVoice.git
```

> 代码内已自动将 `third_party/Matcha-TTS` 加入 sys.path（如位于 `COSYVOICE_ROOT/third_party/Matcha-TTS`），无需手动处理。

### 2. 下载模型权重（约 1.5GB）

```bash
# 方式 A：git clone（ModelScope，国内推荐）
git clone https://www.modelscope.cn/iic/CosyVoice2-0.5B.git ./docker-deploy/.cache/CosyVoice/pretrained_models/CosyVoice2-0.5B

# 方式 B：指定任意目录后配置环境变量
git clone https://www.modelscope.cn/iic/CosyVoice2-0.5B.git /path/to/CosyVoice2-0.5B
export COSYVOICE_MODEL_DIR=/path/to/CosyVoice2-0.5B
```

### 3. 验证下载完整性

```bash
ls -la ./docker-deploy/.cache/CosyVoice/pretrained_models/CosyVoice2-0.5B/
```

应包含：`cosyvoice.yaml`、`llm.pt`、`flow.pt`、`hift.pt`、`speech_tokenizer_v2.onnx`、`spk2info.pt`（预置音色表）等。

### 4. 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `COSYVOICE_MODEL_DIR` | `<cache>/CosyVoice/pretrained_models/CosyVoice2-0.5B` | 模型目录 |
| `COSYVOICE_ROOT` | `<cache>/CosyVoice` | CosyVoice 仓库根（用于定位 Matcha-TTS） |
| `COSYVOICE_FP16` | `0`（CPU 默认 FP32） | GPU 时设 `1` 启用 FP16 加速（约 6-8GB 显存，4bit 量化 ~4GB） |

> 💡 **实际部署路径**（2026-08-18 已落地）：仓库 clone 到 `docker-deploy/.cache/CosyVoice`，
> 模型经 ModelScope `snapshot_download('iic/CosyVoice2-0.5B')` 下载到 `docker-deploy/.cache/cosyvoice-ms`。
> 若模型不在默认路径，设置 `COSYVOICE_MODEL_DIR=<实际模型目录>` 即可（代码会优先读环境变量）。

### 5. 使用

```bash
# 引擎指定：cosyvoice；voice 可选：中文女/中文男/英文女/英文男/粤语女/四川女 等预置音色
curl -X POST http://127.0.0.1:25231/v1/tts/generate \
  -H 'Content-Type: application/json' \
  -d '{"text":"你好，欢迎光临","engine":"cosyvoice","voice":"中文女","sample_rate":16000}'
```

> `engine=auto` 时中文文本将**自动优先使用 cosyvoice**（未安装则依次回退 kokoro → chattts）。

## CosyVoice 3 模型下载（Fun-CosyVoice3-0.5B-2512，Apache 2.0，可商用）

> **高质量 zero-shot 克隆引擎**：9 种语言 + 18 种汉语方言、发音修补、指令控制情感语速。
> **注意**：CosyVoice3 模型包**无预置音色**（不含 spk2info.pt），仅支持 zero_shot/cross_lingual 音色克隆，
> 请求时必须携带参考音频（`reference_audio`，base64 WAV，3~10s 说话人样本），缺参时接口显式报错，不会回退其它引擎。

### 1. 下载模型权重（约 5GB，ModelScope 推荐）

```bash
python -c "from modelscope import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='./docker-deploy/.cache/cosyvoice-ms/FunAudioLLM/Fun-CosyVoice3-0___5B-2512')"
```

### 2. 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `COSYVOICE3_MODEL_DIR` | `<cache>/cosyvoice-ms/FunAudioLLM/Fun-CosyVoice3-0___5B-2512` | CosyVoice3 模型目录 |

### 3. 使用（zero_shot，需参考音频）

```bash
# reference_audio 为 base64 编码的 WAV（3~10s 说话人样本）；reference_text 可选（参考音频文本，自动补 <|endofprompt|>）
curl -X POST http://127.0.0.1:25231/v1/tts/generate \
  -H 'Content-Type: application/json' \
  -d '{"text":"你好，欢迎光临","engine":"cosyvoice3","reference_audio":"<base64 WAV>","reference_text":"可选"}'
```

## Kokoro-82M 模型下载（Apache 2.0，可商用，极轻量）

> **ChatTTS 的可商用替代**：text-only 预置音色（无需参考音频），82M 极轻量（CPU 可跑，约 6 倍实时）。
> 中文自动使用 **v1.1-zh 中文优化版**（100 个中文音色：zf_001~zf_099 女 / zm_009~zm_100 男，数字编号）；
> 英文及其它语言使用 v1.0 标准版（54 音色）。

### 1. 安装

```bash
pip install kokoro>=0.9.0   # pyproject.toml 已声明；依赖 misaki（英文需系统 espeak-ng，Dockerfile 已装）
```

### 2. 下载权重（v1.0 + v1.1-zh 各 ~312MB，HF 镜像）

权重经 HuggingFace 下载，首次运行时自动拉取（走 `KOKORO_HF_ENDPOINT` 镜像，默认 hf-mirror.com）：

```bash
# 预下载到 .cache/kokoro-hf（HF 缓存结构，随 .cache 卷同步，可离线）：
HF_ENDPOINT=https://hf-mirror.com HF_HOME=./docker-deploy/.cache/kokoro-hf \
  python -c "from huggingface_hub import hf_hub_download; hf_hub_download('hexgrad/Kokoro-82M-v1.1-zh', 'kokoro-v1_1-zh.pth'); hf_hub_download('hexgrad/Kokoro-82M', 'kokoro-v1_0.pth')"
```

### 3. 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `KOKORO_HF_HOME` | `<cache>/kokoro-hf` | 权重 HF 缓存目录 |
| `KOKORO_HF_ENDPOINT` | `https://hf-mirror.com` | 权重下载镜像 |
| `KOKORO_REPO_ID_ZH` | `hexgrad/Kokoro-82M-v1.1-zh` | 中文权重仓库（一般无需改） |

### 4. 使用

```bash
# engine=kokoro；voice 可选 zf_001~zf_099 / zm_009~zm_100（中文）/ af_maple（英文女）/ af_sol（英文女）/ bf_vale（英式女）
curl -X POST http://127.0.0.1:25231/v1/tts/generate \
  -H 'Content-Type: application/json' \
  -d '{"text":"你好，欢迎光临","engine":"kokoro","voice":"zf_001","sample_rate":16000}'
```

> `engine=auto` 中文回退链：**cosyvoice → kokoro → chattts**（前两者均 Apache 2.0 可商用，chattts 仅作最终兜底）。

## ChatTTS 模型下载

### ModelScope 模型地址
- **网页浏览**: https://www.modelscope.cn/models/2Noise/ChatTTS
- **模型名称**: `2Noise/ChatTTS`

### 推荐下载方法

#### 方法1：使用 huggingface-cli（推荐）
```bash
cd bookroom-audio
HF_ENDPOINT=https://www.modelscope.cn huggingface-cli download 2Noise/ChatTTS --local-dir ./.cache/models--2Noise--ChatTTS --local-dir-use-symlinks False
```

模型会自动下载到 `.cache/models--2Noise--ChatTTS/` 目录。

#### 方法2：手动下载（从 ModelScope 网页）
1. 访问 https://www.modelscope.cn/models/2Noise/ChatTTS
2. 点击"下载"按钮下载完整模型文件
3. 解压到 `.cache/models--2Noise--ChatTTS/snapshots/{commit_hash}/` 目录

### 验证下载完整性
```bash
ls -la ./.cache/models--2Noise--ChatTTS/snapshots/*/asset/
```

应该看到以下文件：
- `DVAE.safetensors` (~57MB)
- `Decoder.safetensors` (~98MB)
- `Embed.safetensors` (~1GB)
- `Vocos.safetensors` (~1GB)
- `gpt/model.safetensors` (~813MB)
- `tokenizer/tokenizer.json`
- `tokenizer/tokenizer_config.json`
- `tokenizer/special_tokens_map.json`

## 其他 TTS 模型

### MeloTTS 系列

#### ModelScope 模型地址
- **中文**: https://www.modelscope.cn/models/myshell-ai/MeloTTS-Chinese
- **英文**: https://www.modelscope.cn/models/myshell-ai/MeloTTS-English
- **日语**: https://www.modelscope.cn/models/myshell-ai/MeloTTS-Japanese

```bash
# 中文模型
HF_ENDPOINT=https://www.modelscope.cn huggingface-cli download myshell-ai/MeloTTS-Chinese

# 英文模型
HF_ENDPOINT=https://www.modelscope.cn huggingface-cli download myshell-ai/MeloTTS-English

# 日语模型
HF_ENDPOINT=https://www.modelscope.cn huggingface-cli download myshell-ai/MeloTTS-Japanese
```

## ASR 模型

### Qwen3-ASR

#### ModelScope 模型地址
- **网页浏览**: https://www.modelscope.cn/models/Qwen/Qwen3-ASR-1.7B
- **模型名称**: `Qwen/Qwen3-ASR-1.7B`

```bash
HF_ENDPOINT=https://www.modelscope.cn huggingface-cli download Qwen/Qwen3-ASR-1.7B
```

### Whisper 系列（OpenAI 官方版本）

> ⚠️ **安全提示**: 本系统**禁止自动下载** Whisper 模型，必须手动下载 OpenAI 官方版本。
> 
> **原因**: 非官方版本（如 Systran/faster-whisper-*）可能包含广告或恶意代码。

#### ModelScope 模型地址（推荐国内使用）
- **Base**: https://www.modelscope.cn/models/openai/whisper-base
- **Medium**: https://www.modelscope.cn/models/openai/whisper-medium
- **Large-v3**: https://www.modelscope.cn/models/openai/whisper-large-v3

#### 强制手动下载命令

```bash
# 设置阿里 ModelScope 为下载源（国内推荐）
export HF_ENDPOINT=https://www.modelscope.cn

# Base 模型
huggingface-cli download openai/whisper-base

# Medium 模型（推荐）
huggingface-cli download openai/whisper-medium

# Large-v3 模型
huggingface-cli download openai/whisper-large-v3
```

#### 备选下载方式（官方 Hugging Face）

```bash
# 设置官方 Hugging Face 为下载源（国外）
export HF_ENDPOINT=https://huggingface.co

# Medium 模型
huggingface-cli download openai/whisper-medium
```

#### ✅ 支持的官方模型
| 模型名称 | 大小 | 说明 |
|---------|------|------|
| `tiny` / `tiny.en` | ~75MB | 最小模型，速度最快 |
| `base` / `base.en` | ~142MB | 基础模型 |
| `small` / `small.en` | ~466MB | 小型模型 |
| `medium` / `medium.en` | ~1.5GB | 中等模型（推荐） |
| `large-v3` | ~3.0GB | 大型模型，效果最好 |
| `distil-large-v3` | ~1.5GB | 蒸馏版大型模型 |

#### ❌ 不推荐的非官方模型
- `Systran/faster-whisper-*` - 第三方修改版本，可能包含广告
- 其他非 `openai/` 前缀的 Whisper 模型

#### 模型缓存位置
下载后模型会自动存放在 `.cache/models--openai--whisper-{model_name}` 目录下。

## 环境变量配置

### .env 文件配置
```
# 服务器配置
SERVER_HOST=0.0.0.0
SERVER_PORT=15231
SERVER_WORKERS=1

# 模型配置
MODEL=medium
LANGUAGE=en
DEVICE=cpu
COMPUTE_TYPE=int8
MODEL_KEEP_ALIVE=5m
NUM_WORKERS=4

# 缓存配置（统一管理所有模型）
CACHE_DIR=./docker-deploy/.cache
LOCAL_FILES_ONLY=False
HF_ENDPOINT=https://www.modelscope.cn
```

### 命令行参数
```bash
# 启动服务器（使用统一缓存目录）
python -m bookroom_audio.server --engine qwen-asr --local-files-only true

# 自定义缓存目录
python -m bookroom_audio.server --cache-dir /path/to/cache --local-files-only true
```

## 离线模式

### 启用离线模式
```bash
# 方法1：命令行参数
python -m bookroom_audio.server --local-files-only true

# 方法2：环境变量
export LOCAL_FILES_ONLY=true
python -m bookroom_audio.server
```

### 离线模式说明
- `--local-files-only true`：只使用本地文件，不尝试网络下载
- 系统会自动设置 `TRANSFORMERS_OFFLINE` 和 `HF_HUB_OFFLINE` 环境变量
- 确保所有模型文件已完整下载到 `.cache` 目录

## 模型加载说明

### 首次加载
- 模型会在首次请求时自动加载
- ChatTTS 加载时间约 1-2 分钟
- Whisper 加载时间约 30 秒 - 1 分钟
- Qwen3-ASR 加载时间约 1 分钟

### 模型缓存
- 模型加载后会缓存在内存中
- 可通过 `--model-keep-alive` 参数设置缓存时间
- 默认缓存 5 分钟后自动卸载

## 流式 ASR 模型（FunASR / SenseVoice）

实时流式语音识别支持三种引擎，对应不同的模型下载需求。

### 引擎与模型对应关系

| 引擎 | 需要下载的模型 | 说明 |
|------|--------------|------|
| `funasr-server` | 无需下载（代理外部服务） | 外部 FunASR 服务自行管理模型 |
| `funasr-local` | paraformer-zh-streaming + **paraformer-zh** + fsmn-vad + ct-punc | 进程内 FunASR 流式；paraformer-zh 为 2pass 离线纠错模型（FINAL 阶段整句重识别 + 字级时间戳） |
| `sensevoice-local` | SenseVoiceSmall + fsmn-vad | 进程内 SenseVoice |

### FunASR 流式模型下载

通过 ModelScope（国内推荐）：

```bash
# 设置环境变量
export HF_ENDPOINT=https://www.modelscope.cn

# Paraformer-zh-streaming（流式语音识别主模型）
huggingface-cli download iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online

# Paraformer-zh（2pass 离线精确模型，FINAL 阶段整句重识别纠正同音字错误，并输出字级时间戳）
huggingface-cli download iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch

# FSMN-VAD（端点检测）
huggingface-cli download iic/speech_fsmn_vad_zh-cn-16k-common-pytorch

# CT-Punc（标点恢复）
huggingface-cli download iic/punc_ct-transformer_cn-en-common-vocab471067-large
```

或在 `.env` 中指定本地模型路径：
```bash
STREAMING_ASR_MODEL=/path/to/paraformer-zh-streaming
STREAMING_OFFLINE_MODEL=/path/to/paraformer-zh
STREAMING_VAD_MODEL=/path/to/fsmn-vad
STREAMING_PUNC_MODEL=/path/to/ct-punc
```

### SenseVoice 模型下载

```bash
export HF_ENDPOINT=https://www.modelscope.cn

# SenseVoiceSmall（支持多语言、情感、事件检测）
huggingface-cli download iic/SenseVoiceSmall
```

或在 `.env` 中指定：
```bash
STREAMING_SENSEVOICE_MODEL=/path/to/SenseVoiceSmall
```

### FunASR Server 模式（无需下载模型）

如果使用 `funasr-server` 引擎，模型由外部 FunASR 服务管理，本机无需下载：

1. 部署外部 FunASR 服务（参考 [FunASR 官方文档](https://github.com/modelscope/FunASR)）
2. 启动 `serve_realtime_ws.py` 流式服务
3. 在 `.env` 中配置服务地址：
```bash
STREAMING_ASR_ENGINE=funasr-server
STREAMING_FUNASR_SERVER_URL=ws://<funasr-host>:<funasr-port>
```

### 验证流式 ASR 引擎可用性

启动服务后访问引擎列表接口：
```bash
curl http://localhost:15231/v1/audio/streaming/engines
```

返回示例：
```json
{
  "engines": [
    {"engine": "funasr-server", "available": true, "description": "..."},
    {"engine": "funasr-local", "available": true, "description": "..."},
    {"engine": "sensevoice-local", "available": false, "description": "..."}
  ],
  "default_engine": "funasr-local"
}
```

## 目录结构

```
.cache/
├── models--2Noise--ChatTTS/              # ChatTTS (2.3GB)
├── models--myshell-ai--MeloTTS-Chinese/  # MeloTTS 中文 (396MB)
├── models--myshell-ai--MeloTTS-English/  # MeloTTS 英文 (396MB)
├── models--myshell-ai--MeloTTS-Japanese/ # MeloTTS 日语 (396MB)
├── models--Qwen--Qwen3-ASR-1.7B/        # Qwen3-ASR
├── models--Systran--faster-whisper-base/    # Whisper Base
├── models--Systran--faster-whisper-medium/  # Whisper Medium
└── models--Systran--faster-whisper-large-v3/ # Whisper Large-v3
```

## 故障排除

### 模型下载失败
1. 检查网络连接
2. 确认 `HF_ENDPOINT` 环境变量设置正确
3. 尝试手动下载模型文件

### 模型文件不完整
1. 检查 `.cache` 目录中的模型文件
2. 重新下载缺失的文件
3. 使用 `--local-files-only false` 允许自动下载

### 离线模式无法加载模型
1. 确认所有模型文件已完整下载
2. 检查文件权限
3. 验证缓存目录路径正确