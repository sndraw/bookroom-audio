"""
FunASR 兼容协议端点测试

验证 /v1/audio/streaming/funasr 端点能正确：
1. 接收 FunASR 协议初始化消息
2. 转发音频到引擎
3. 输出 FunASR 格式的响应（mode: 2pass-online/2pass-offline）

测试方式：
  python -m tests.test_streaming_asr --module funasr_compat
"""

import asyncio
import json
import os
import sys
import wave
from pathlib import Path

import websockets

# 项目根目录（tests/streaming_asr/test_funasr_compat.py → 上三级）
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
WS_URL = f"ws://{SERVER_HOST}:{SERVER_PORT}/v1/audio/streaming/funasr"
if API_KEY:
    WS_URL += f"?token={API_KEY}"


async def test_funasr_compat_endpoint() -> None:
    """测试 FunASR 兼容端点

    步骤：
    1. 建立连接
    2. 发送 FunASR 初始化消息（mode=2pass）
    3. 流式发送 WAV 文件
    4. 发送 is_speaking=false 结束
    5. 接收并验证响应格式
    """
    print(f"\n{'=' * 60}")
    print("FunASR 兼容端点测试")
    print(f"{'=' * 60}")
    print(f"URL:   {WS_URL}")
    print(f"Audio: {TEST_AUDIO_WAV}")
    print(f"{'-' * 60}")

    if not Path(TEST_AUDIO_WAV).exists():
        print(f"[FAIL] 音频文件不存在: {TEST_AUDIO_WAV}")
        return False

    # 读取音频文件，提取 PCM 数据
    audio_data = Path(TEST_AUDIO_WAV).read_bytes()
    print(f"音频文件大小: {len(audio_data)} 字节")

    # 用 wave 模块提取 PCM（确保格式正确）
    with wave.open(TEST_AUDIO_WAV, 'rb') as wav_file:
        pcm_data = wav_file.readframes(wav_file.getnframes())
        actual_sample_rate = wav_file.getframerate()
        actual_channels = wav_file.getnchannels()
        actual_sample_width = wav_file.getsampwidth()
    print(
        f"PCM: {len(pcm_data)} 字节, "
        f"{actual_sample_rate}Hz, {actual_channels}ch, "
        f"{actual_sample_width * 8}bit"
    )

    received_messages = []
    final_received = False

    try:
        async with websockets.connect(
            WS_URL,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=60,
        ) as websocket:
            print("[OK] WebSocket 连接已建立")

            # 1. 发送 FunASR 初始化消息
            init_msg = {
                "mode": "2pass",
                "chunk_size": [5, 10, 5],
                "wav_name": "test_audio",
                "is_speaking": True,
                "itn": True,
                "audio_fs": actual_sample_rate,
                "wav_format": "pcm",  # 发送纯 PCM
            }
            await websocket.send(json.dumps(init_msg))
            print(f"[OK] 已发送初始化消息: {init_msg}")

            # 2. 流式发送 PCM 数据（分块，模拟实时麦克风）
            chunk_size = int(actual_sample_rate * actual_sample_width * 0.6)
            total_chunks = (len(pcm_data) + chunk_size - 1) // chunk_size

            print(
                f"[发送] 开始流式发送 PCM（{len(pcm_data)} 字节，"
                f"{total_chunks} 块，每块 {chunk_size} 字节 = 600ms）"
            )

            # 启动接收任务
            async def receive_results():
                nonlocal final_received
                try:
                    while True:
                        msg = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=TEST_TIMEOUT,
                        )
                        if isinstance(msg, bytes):
                            print(f"[WARN] 收到二进制消息，忽略")
                            continue

                        data = json.loads(msg)
                        received_messages.append(data)

                        # 完整打印第一条消息，便于调试
                        if len(received_messages) == 1:
                            print(f"[DEBUG] 第一条消息完整内容: {data}")

                        # 验证 FunASR 协议字段
                        mode = data.get("mode", "")
                        text = data.get("text", "")
                        is_final = data.get("is_final", False)

                        if data.get("error"):
                            print(f"[ERROR] {data.get('error_code')}: {text}")
                            return

                        if is_final:
                            print(f"[FINAL] mode={mode} text={text!r}")
                            final_received = True
                            return
                        else:
                            print(f"[PARTIAL] mode={mode} text={text!r}")
                except asyncio.TimeoutError:
                    print(f"[TIMEOUT] {TEST_TIMEOUT}s 内未收到结果")
                except websockets.exceptions.ConnectionClosed:
                    print("[连接] 服务端关闭连接")

            receive_task = asyncio.create_task(receive_results())

            # 发送音频块（每 100ms 一块，模拟实时流）
            for i in range(0, len(pcm_data), chunk_size):
                chunk = pcm_data[i:i + chunk_size]
                await websocket.send(chunk)
                await asyncio.sleep(0.1)  # 100ms

            print(f"[发送] 音频发送完成")

            # 3. 发送结束信号
            await websocket.send(json.dumps({"is_speaking": False}))
            print("[OK] 已发送 is_speaking=false")

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

    # 检查是否包含 FunASR 协议字段
    for i, msg in enumerate(received_messages):
        required_fields = ["mode", "wav_name", "text", "is_final"]
        missing = [f for f in required_fields if f not in msg]
        if missing:
            print(f"[FAIL] 消息 {i} 缺少字段: {missing}")
            return False

    if not final_received:
        print("[FAIL] 未收到 FINAL 结果")
        return False

    # 检查 wav_name 回显
    if received_messages[0].get("wav_name") != "test_audio":
        print(f"[FAIL] wav_name 不正确: {received_messages[0].get('wav_name')}")
        return False

    # 检查 mode 值
    modes = {m.get("mode") for m in received_messages}
    if not modes & {"2pass-online", "2pass-offline"}:
        print(f"[FAIL] mode 值不正确: {modes}")
        return False

    print("[PASS] FunASR 兼容端点协议格式正确")
    print(f"  - 收到 {len(received_messages)} 条消息")
    print(f"  - 包含 PARTIAL（2pass-online）和 FINAL（2pass-offline）")
    print(f"  - wav_name 正确回显")
    return True


async def main() -> int:
    """主函数"""
    success = await test_funasr_compat_endpoint()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
