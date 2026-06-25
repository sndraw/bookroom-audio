"""
bookroom-audio 流式 ASR 端到端测试

统一测试入口，按模块拆分：
- native：原生协议端点测试
- funasr_compat：FunASR 兼容协议端点测试

使用方式：
  python -m tests.streaming_asr                      # 运行所有模块
  python -m tests.streaming_asr --module native      # 只测原生协议
  python -m tests.streaming_asr --module funasr_compat  # 只测 FunASR 兼容

环境变量：
  SERVER_HOST  - 服务端地址（默认 127.0.0.1）
  SERVER_PORT  - 服务端端口（默认 15231）
  API_KEY      - API Key（默认 test_api_key）
  TEST_AUDIO_WAV - 测试音频文件路径
  TEST_TIMEOUT - 单次测试超时秒数（默认 120）
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 项目根目录（tests/streaming_asr/__main__.py → 上三级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ==================== 模块注册 ====================

MODULES = {
    "native": "tests.streaming_asr.test_native",
    "funasr_compat": "tests.streaming_asr.test_funasr_compat",
}


async def run_module(name: str, module_path: str) -> bool:
    """运行单个测试模块"""
    print(f"\n{'#' * 60}")
    print(f"# 运行模块: {name}")
    print(f"{'#' * 60}")

    try:
        module = __import__(module_path, fromlist=["main"])
        exit_code = await module.main()
        return exit_code == 0
    except Exception as e:
        print(f"[FAIL] 模块 {name} 异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main_async(modules_to_run: list) -> int:
    """主函数：按顺序运行测试模块"""
    print("=" * 60)
    print("bookroom-audio 流式 ASR 端到端测试")
    print("=" * 60)
    print(f"Server:  {os.getenv('SERVER_HOST', '127.0.0.1')}:"
          f"{os.getenv('SERVER_PORT', '15231')}")
    print(f"Audio:   {os.getenv('TEST_AUDIO_WAV', 'tests/real_chinese_audio.wav')}")
    print(f"Modules: {', '.join(modules_to_run)}")
    print("=" * 60)

    results = {}
    for name in modules_to_run:
        module_path = MODULES.get(name)
        if module_path is None:
            print(f"[WARN] 未知模块: {name}，跳过")
            continue
        success = await run_module(name, module_path)
        results[name] = success

    # 汇总
    print(f"\n{'=' * 60}")
    print("测试汇总")
    print(f"{'=' * 60}")
    for name, success in results.items():
        status = "PASS" if success else "FAIL"
        print(f"  {name:20s} [{status}]")

    all_pass = all(results.values())
    print(f"\n{'=' * 60}")
    print(f"总体结果: {'ALL PASS' if all_pass else 'FAILED'}")
    print(f"{'=' * 60}")

    return 0 if all_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="bookroom-audio 流式 ASR 端到端测试"
    )
    parser.add_argument(
        "--module", "-m",
        nargs="+",
        choices=list(MODULES.keys()),
        default=list(MODULES.keys()),
        help="指定测试模块（默认全部）",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args.module))


if __name__ == "__main__":
    sys.exit(main())
