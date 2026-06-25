# 配置管理系统

## 概述

BookRoom Audio 使用统一的配置管理系统来管理所有服务器、模型和缓存相关的配置参数。

## 配置文件

### 环境变量配置 (.env)

```bash
# 服务器配置
SERVER_DEBUG=false
SERVER_HOST=0.0.0.0
SERVER_PORT=15231
SERVER_WORKERS=1
API_KEY=test_api_key

# TTS 配置
TTS_ENGINE=chattts
TTS_LANGUAGE=zh

# ASR 配置
ASR_ENGINE=qwen-asr
ASR_MODEL=medium
ASR_LANGUAGE=zh

# 通用模型配置
DEVICE=cpu
COMPUTE_TYPE=int8
MODEL_KEEP_ALIVE=5m
NUM_WORKERS=4

# 缓存配置
CACHE_DIR=./docker-deploy/.cache
LOCAL_FILES_ONLY=False
HF_ENDPOINT=https://www.modelscope.cn
```

### Docker 部署配置

```bash
# docker-deploy/.env 文件
# 缓存配置（容器内绝对路径）
CACHE_DIR=/app/.cache
LOCAL_FILES_ONLY=False
HF_ENDPOINT=https://www.modelscope.cn
```

**注意事项**：
- Docker 容器内必须使用绝对路径（如 `/app/.cache`）
- 不能使用相对路径（如 `./.cache`），因为容器工作目录是 `/app`
- Volume 挂载：`./docker-deploy/.cache:/app/.cache`（宿主机相对路径:容器绝对路径）
- 开发环境默认使用 `./docker-deploy/.cache`，与 Docker 部署共用同一缓存目录，方便模型迁移
- FunASR/ModelScope 模型会下载到 `$CACHE_DIR/models/iic/` 子目录

### 命令行参数

```bash
python -m bookroom_audio.server \
  --engine qwen-asr \
  --model medium \
  --device cpu \
  --local-files-only true \
  --cache-dir ./.cache
```

## 配置优先级

配置参数的优先级（从高到低）：

1. **命令行参数** - 最高优先级
2. **环境变量** - 中等优先级
3. **默认值** - 最低优先级

## 配置结构

### ServerConfig - 服务器配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | str | `"0.0.0.0"` | 服务器监听地址 |
| `port` | int | `15231` | 服务器端口 |
| `workers` | int | `1` | 工作进程数 |
| `debug` | bool | `false` | 调试模式 |
| `api_key` | str | `None` | API密钥 |
| `reload` | bool | `false` | 自动重载 |
| `ssl` | bool | `false` | 启用SSL |

### ModelConfig - 模型配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| **ASR 配置** | | | |
| `asr_engine` | str | `"qwen-asr"` | ASR引擎 (whisper, qwen-asr) |
| `asr_model` | str | `"medium"` | ASR模型大小 |
| `asr_language` | str | `"zh"` | ASR默认语言 |
| **TTS 配置** | | | |
| `tts_engine` | str | `"chattts"` | TTS引擎 (chattts, melotts) |
| `tts_language` | str | `"zh"` | TTS默认语言 |
| **流式 ASR 配置** | | | |
| `streaming_asr_engine` | str | `"funasr-local"` | 流式ASR引擎 (funasr-server, funasr-local, sensevoice-local) |
| `streaming_asr_model` | str | `"paraformer-zh-streaming"` | FunASR 流式模型 |
| `streaming_vad_model` | str | `"fsmn-vad"` | VAD 端点检测模型 |
| `streaming_punc_model` | str | `"ct-punc"` | 标点恢复模型 |
| `streaming_sensevoice_model` | str | `"iic/SenseVoiceSmall"` | SenseVoice 模型（sensevoice-local 引擎使用） |
| `streaming_enable_punc` | bool | `true` | 是否启用标点恢复 |
| `streaming_chunk_ms` | int | `600` | 音频分块毫秒数 |
| `streaming_funasr_server_url` | str | `None` | 外部 FunASR 服务地址（仅 funasr-server 引擎需要，格式 ws://host:port） |
| **通用配置** | | | |
| `device` | str | `"cpu"` | 运行设备 (cpu, cuda) |
| `compute_type` | str | `"int8"` | 计算类型 |
| `model_keep_alive` | str | `"5m"` | 模型缓存时间 |
| `num_workers` | int | `"1"` | 工作线程数 |

**兼容性说明**：
- `engine` 属性：返回 `asr_engine`（兼容旧代码）
- `model` 属性：返回 `asr_model`（兼容旧代码）
- `language` 属性：返回 `asr_language`（兼容旧代码）

### CacheConfig - 缓存配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cache_dir` | str | `"./.cache"` | 缓存目录 |
| `local_files_only` | bool | `true` | 仅使用本地文件 |
| `transformers_offline` | bool | `true` | Transformers离线模式 |
| `hf_datasets_offline` | bool | `true` | HF数据集离线模式 |
| `hf_endpoint` | str | `"https://www.modelscope.cn"` | Hugging Face镜像 |
| `model_source` | str | `"huggingface"` | 模型源 |

## 使用示例

### 基本使用

```python
from bookroom_audio.utils.config import get_config

# 获取全局配置
config = get_config()

# 访问配置
print(f"服务器地址: {config.server.host}")
print(f"模型引擎: {config.model.engine}")
print(f"缓存目录: {config.cache.cache_dir}")
```

### 命令行参数解析

```python
from bookroom_audio.utils.utils_api import parse_args

# 解析命令行参数
args = parse_args()

# 访问参数
print(f"引擎: {args.model.engine}")
print(f"离线模式: {args.cache.local_files_only}")
```

### 环境变量设置

```bash
# 设置缓存目录
export CACHE_DIR=/path/to/cache

# 设置离线模式
export LOCAL_FILES_ONLY=true

# 设置Hugging Face镜像
export HF_ENDPOINT=https://www.modelscope.cn
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

当启用离线模式时，系统会：

1. 设置 `TRANSFORMERS_OFFLINE=1`
2. 设置 `HF_HUB_OFFLINE=1`
3. 设置 `HF_DATASETS_OFFLINE=1`
4. 所有模型加载使用 `local_files_only=True`

## 缓存目录管理

### 统一缓存目录结构

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

### 自定义缓存目录

```bash
# 方法1：环境变量
export CACHE_DIR=/custom/cache/path
python -m bookroom_audio.server

# 方法2：命令行参数
python -m bookroom_audio.server --cache-dir /custom/cache/path
```

## 配置验证

### 查看当前配置

启动服务器时会显示配置摘要：

```
============================================================
📋 应用配置摘要
============================================================
🖥️  服务器配置:
  - Host: 0.0.0.0
  - Port: 15231
  - Workers: 1
  - Debug: False
  - API Key: 未设置
🤖 模型配置:
  - Engine: qwen-asr
  - Model: medium
  - Language: en
  - Device: cpu
  - Compute Type: int8
  - Model Keep Alive: 5m
💾 缓存配置:
  - Cache Dir: ./.cache
  - Local Files Only: True
  - Transformers Offline: True
  - HF Datasets Offline: True
  - HF Endpoint: https://www.modelscope.cn
  - Model Source: huggingface
============================================================
```

### 编程方式验证

```python
from bookroom_audio.utils.config import print_config_summary

# 打印配置摘要
print_config_summary()
```

## 故障排除

### 配置未生效

1. 检查环境变量是否正确设置
2. 确认命令行参数优先级
3. 验证 .env 文件格式

### 离线模式失败

1. 确认模型文件已完整下载
2. 检查缓存目录权限
3. 验证离线模式环境变量

### 缓存目录问题

1. 确认缓存目录存在且可写
2. 检查磁盘空间
3. 验证路径格式

## 最佳实践

1. **使用环境变量管理配置**：便于在不同环境间切换
2. **启用离线模式**：提高稳定性和性能
3. **统一缓存目录**：便于管理和维护
4. **定期清理缓存**：释放磁盘空间
5. **配置版本控制**：将 .env.example 加入版本控制

## 相关文件

- `bookroom_audio/utils/config.py` - 配置管理核心模块
- `bookroom_audio/utils/utils_api.py` - 参数解析和API工具
- `.env` - 环境变量配置文件
- `.env.example` - 环境变量示例文件