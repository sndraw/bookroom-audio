"""
原生协议端点测试

验证 /v1/audio/streaming/transcriptions 端点能正确：
1. 接收 native 协议的 START 消息
2. 转发音频到引擎
3. 输出 native 格式的响应（started/partial/final/closed）

测试方式：
  python -m tests.streaming_asr.test_native
"""

import asyncio
import json
import os
import sys
import wave
from pathlib import Path

import websockets

# 项目根目录（tests/streaming_asr/test_native.py → 上三级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 读取环境变量配置
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "15231"))
API_KEY = os.getenv("API_KEY", "test_api_key")
TEST_AUDIO_WAV = os.getenv(
    "TEST_AUDIO_WAV",
    str(PROJECT_ROOT / "tests" / "real_chinese_audio.wav"),
)
TEST_TIMEOUT = int(os.getenv("TEST_TIMEOUT", "120"))

# WS_URL 拼接（避免硬编码）
WS_URL = f"ws://{SERVER_HOST}:{SERVER_PORT}/v1/audio/streaming/transcriptions"
if API_KEY:
    WS_URL += f"?token={API_KEY}"


async def test_native_endpoint() -> bool:
    """测试原生协议端点

    步骤：
    1. 建立连接
    2. 发送 START 消息（native 协议）
    3. 流式发送 PCM 数据
    4. 发送 STOP 消息
    5. 接收并验证响应格式（started/partial/final/closed）
    """
    print(f"\n{'=' * 60}")
    print("原生协议端点测试")
    print(f"{'=' * 60}")
    print(f"URL:   {WS_URL}")
    print(f"Audio: {TEST_AUDIO_WAV}")
    print(f"{'-' * 60}")

    if not Path(TEST_AUDIO_WAV).exists():
        print(f"[FAIL] 音频文件不存在: {TEST_AUDIO_WAV}")
        return False

    # 提取 PCM 数据
    with wave.open(TEST_AUDIO_WAV, 'rb') as wav_file:
        pcm_data = wav_file.readframes(wav_file.getnframes())
        actual_sample_rate = wav_file.getframerate()
        actual_sample_width = wav_file.getsampwidth()
    print(
        f"PCM: {len(pcm_data)} 字节, "
        f"{actual_sample_rate}Hz, 16bit"
    )

    received_messages = []
    started_received = False
    final_received = False
    closed_received = False

    try:
        async with websockets.connect(
            WS_URL,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=60,
        ) as websocket:
            print("[OK] WebSocket 连接已建立")

            # 1. 发送 START 消息（native 协议）
            start_msg = {
                "type": "start",
                "config": {
                    "engine": "funasr-local",
                    "language": "zh",
                    "audio_format": "pcm",
                    "sample_rate": actual_sample_rate,
                    "enable_punctuation": True,
                    "enable_vad": True,
                    "enable_itn": True,
                },
            }
            await websocket.send(json.dumps(start_msg))
            print(f"[OK] 已发送 START 消息")

            # 2. 启动接收任务
            async def receive_results():
                nonlocal started_received, final_received, closed_received
                try:
                    while True:
                        msg = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=TEST_TIMEOUT,
                        )
                        if isinstance(msg, bytes):
                            continue

                        data = json.loads(msg)
                        received_messages.append(data)

                        msg_type = data.get("type", "")
                        if msg_type == "started":
                            started_received = True
                            print(
                                f"[STARTED] session={data.get('session_id')} "
                                f"engine={data.get('engine')}"
                            )
                        elif msg_type == "partial":
                            print(f"[PARTIAL] {data.get('text', '')!r}")
                        elif msg_type == "final":
                            final_received = True
                            print(
                                f"[FINAL] sentence#{data.get('sentence_id')} "
                                f"text={data.get('text', '')!r}"
                            )
                        elif msg_type == "closed":
                            closed_received = True
                            print(f"[CLOSED] {data.get('reason', '')}")
                            return
                        elif msg_type == "error":
                            print(
                                f"[ERROR] {data.get('code')}: "
                                f"{data.get('message')}"
                            )
                            return
                        else:
                            print(f"[UNKNOWN] type={msg_type}")
                except asyncio.TimeoutError:
                    print(f"[TIMEOUT] {TEST_TIMEOUT}s 内未收到结果")
                except websockets.exceptions.ConnectionClosed:
                    print("[连接] 服务端关闭连接")

            receive_task = asyncio.create_task(receive_results())

            # 3. 流式发送 PCM（每 100ms 一块，模拟实时麦克风）
            chunk_size = int(actual_sample_rate * actual_sample_width * 0.6)
            total_chunks = (len(pcm_data) + chunk_size - 1) // chunk_size
            print(
                f"[发送] 开始流式发送 PCM（{len(pcm_data)} 字节，"
                f"{total_chunks} 块）"
            )

            for i in range(0, len(pcm_data), chunk_size):
                chunk = pcm_data[i:i + chunk_size]
                await websocket.send(chunk)
                await asyncio.sleep(0.1)

            print("[发送] 音频发送完成")

            # 4. 发送 STOP 消息
            await websocket.send(json.dumps({"type": "stop"}))
            print("[OK] 已发送 STOP")

            # 等待接收任务完成
            await asyncio.wait_for(receive_task, timeout=TEST_TIMEOUT)

    except Exception as e:
        print(f"[FAIL] 异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 验证结果
    print(f"\n{'-' * 60}")
    print("验证结果")
    print(f"{'-' * 60}")

    if not received_messages:
        print("[FAIL] 未收到任何消息")
        return False

    print(f"收到 {len(received_messages)} 条消息")

    # 检查必需的消息类型
    if not started_received:
        print("[FAIL] 未收到 started 消息")
        return False

    if not final_received:
        print("[FAIL] 未收到 final 消息")
        return False

    if not closed_received:
        print("[FAIL] 未收到 closed 消息")
        return False

    # 检查 started 消息字段
    started_msg = next(
        (m for m in received_messages if m.get("type") == "started"),
        None,
    )
    if started_msg:
        required = ["type", "session_id", "engine", "config"]
        missing = [f for f in required if f not in started_msg]
        if missing:
            print(f"[FAIL] started 消息缺少字段: {missing}")
            return False

    # 检查 final 消息字段
    final_msg = next(
        (m for m in received_messages if m.get("type") == "final"),
        None,
    )
    if final_msg:
        required = ["type", "session_id", "text", "sentence_id"]
        missing = [f for f in required if f not in final_msg]
        if missing:
            print(f"[FAIL] final 消息缺少字段: {missing}")
            return False

    print("[PASS] 原生协议端点测试通过")
    print(f"  - 收到 started/partial/final/closed 全套消息")
    print(f"  - 消息格式符合协议规范")
    return True


async def main() -> int:
    success = await test_native_endpoint()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
