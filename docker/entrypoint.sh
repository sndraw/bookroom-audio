#!/bin/bash
set -e

cd /app

if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

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

# Use uv run to activate the virtual environment and run the server
uv run python -m bookroom_audio.server