#!/bin/bash
set -e

cd /app

if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# ================================================================
# CPU 兼容性运行时环境变量
# 解决 "Illegal instruction" 崩溃问题：
# PyTorch / ctranslate2 预编译 wheel 默认使用 AVX2 指令集，
# 在老旧 CPU / 部分虚拟化 / 不支持 AVX2 的机器上执行会触发 SIGILL。
# 这些环境变量告诉它们在运行时降级到 SSE4/通用 x86-64 指令集。
# ================================================================
export PYTORCH_DISABLE_AVX2="${PYTORCH_DISABLE_AVX2:-1}"
export PYTORCH_DISABLE_AVX512_F="${PYTORCH_DISABLE_AVX512_F:-1}"
export MAX_ISA="${MAX_ISA:-SSE4}"
export CTRANSLATE2_DISABLE_AVX2="${CTRANSLATE2_DISABLE_AVX2:-1}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting bookroom-audio server..."
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Environment:"
echo "  - TTS_ENGINE: ${TTS_ENGINE:-chattts}"
echo "  - TTS_LANGUAGE: ${TTS_LANGUAGE:-zh}"
echo "  - ASR_ENGINE: ${ASR_ENGINE:-qwen-asr}"
echo "  - ASR_MODEL: ${ASR_MODEL:-medium}"
echo "  - ASR_LANGUAGE: ${ASR_LANGUAGE:-zh}"
echo "  - VL_MODEL: ${VL_MODEL:-medium}"
echo "  - VL_FRAME_INTERVAL: ${VL_FRAME_INTERVAL:-10}"
echo "  - DEVICE: ${DEVICE:-auto}"
echo "  - COMPUTE_TYPE: ${COMPUTE_TYPE:-float16}"
echo "  - NUM_WORKERS: ${NUM_WORKERS:-2}"
echo "  - PYTORCH_DISABLE_AVX2: ${PYTORCH_DISABLE_AVX2}"
echo "  - MAX_ISA: ${MAX_ISA}"

# Activate virtual environment and run server
source .venv/bin/activate
python -m bookroom_audio.server