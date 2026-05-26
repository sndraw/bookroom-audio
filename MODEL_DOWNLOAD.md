# 模型下载和缓存说明

## 统一缓存目录

所有模型（TTS 和 ASR）现在统一存储在 `.cache` 目录下，便于管理和维护。

## 模型下载源配置

推荐使用阿里 ModelScope 作为模型下载源（国内访问更稳定）：

```bash
# 设置环境变量
export HF_ENDPOINT=https://www.modelscope.cn

# 或在 .env 文件中配置
HF_ENDPOINT=https://www.modelscope.cn
```

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
CACHE_DIR=./.cache
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