"""
Kokoro pred_dur → 词级时间戳 单元测试（不依赖 kokoro 库，纯数学验证）。

背景：Kokoro-82M（StyleTTS2 架构）模型原生输出 pred_dur（每音素时长帧数），
累计可得字级时间戳，用于数智人 viseme 口型驱动。
pred_dur 结构：[<bos>, ...逐字符对应 phonemes(含空格)..., <eos>]，len = len(phonemes)+2。
换算：1 pred_dur 帧 = 600 采样点 @24kHz；半帧计数，MAGIC_DIVISOR=80（半帧/秒）。
"""

import numpy as np
import pytest

from bookroom_audio.api.routers.tts.engines import _kokoro_timestamps


def approx(a, b, tol=0.5):
    assert abs(a - b) <= tol, f"{a} != {b} (tol {tol})"


def test_two_words_with_space_half_split():
    """两词 'aa bb'：空格半切——前半归前词尾，后半给后词头。
    pred_dur = [bos, a, a, ' ', b, b, eos]"""
    words = _kokoro_timestamps("aa bb", [10, 3, 4, 5, 6, 7, 8], 24000)
    assert len(words) == 2
    w1, w2 = words
    # bos: left=2*max(0,10-3)=14 half-frames → 14/80*1000 = 175ms
    approx(w1["start_ms"], 175)
    # w1 end = (14 + 2*(3+4))/80*1000 = 350ms
    approx(w1["end_ms"], 350)
    assert w1["text"] == "aa"
    # 空格半切：left=28+5=33 half-frames → 412.5；right=38 → w2 start = 38/80*1000 = 475ms
    approx(w2["start_ms"], 475)
    # w2 end = (38 + 2*(6+7))/80*1000 = 800ms
    approx(w2["end_ms"], 800)
    assert w2["text"] == "bb"


def test_single_word_no_space():
    """无空格（中文退化场景）：整句聚合为一个 entry，时间连续累计"""
    words = _kokoro_timestamps("nihao", [10, 2, 3, 4, 5, 6, 8], 24000)
    assert len(words) == 1 and words[0]["text"] == "nihao"
    approx(words[0]["start_ms"], 175)
    approx(words[0]["end_ms"], (14 + 2 * (2 + 3 + 4 + 5 + 6)) / 80 * 1000)


def test_short_pred_dur_returns_empty():
    """pred_dur < 3（不足 <bos>, 音素, <eos>）返回空列表"""
    assert _kokoro_timestamps("ab", [5, 5]) == []


def test_numpy_int64_input():
    """兼容 numpy/torch LongTensor 输入"""
    words = _kokoro_timestamps("x", np.array([10, 3, 4], dtype=np.int64), 24000)
    assert len(words) == 1
    approx(words[0]["start_ms"], 175)
    approx(words[0]["end_ms"], 250)


def test_timestamps_monotonic():
    """所有 start/end 非负且 end >= start"""
    cases = [
        ("aa bb", [10, 3, 4, 5, 6, 7, 8]),
        ("ni hao shi jie", [10, 2, 3, 5, 4, 2, 5, 3, 6, 4, 3, 5, 2, 7, 8]),
        ("x", [10, 3, 4]),
    ]
    for phonemes, pred in cases:
        for w in _kokoro_timestamps(phonemes, pred, 24000):
            assert w["end_ms"] >= w["start_ms"] >= 0
