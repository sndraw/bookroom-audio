"""
视频分析 API 路由模块。

提供基于 Qwen3-VL 模型的视频内容分析功能，包括：
- 视频内容识别（recognize）：描述视频中的视觉内容
- 视频内容评分（score）：对视频内容进行质量和适宜性评分
- 视频内容监测（moderate）：检测是否包含违规内容
- 完整分析（full）：同时进行识别、评分和监测

API 端点:
- POST /v1/video/recognize - 识别视频内容
- POST /v1/video/score - 视频内容评分
- POST /v1/video/moderate - 视频内容监测
- POST /v1/video/analyze - 完整视频分析
- GET /v1/video/models - 获取支持的模型列表
- GET /v1/video/tasks - 获取支持的任务类型
- GET /v1/video/status - 获取 VL 模型状态
"""

import asyncio
import tempfile
import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from bookroom_audio.utils.utils_api import (
    get_api_key_dependency,
    logger,
)

router = APIRouter(
    prefix="/v1/video",
    tags=["video"],
    responses={
        400: {"description": "Invalid request parameters"},
        401: {"description": "Unauthorized - Invalid API key"},
        500: {"description": "Internal server error"},
        503: {"description": "Service unavailable - VL model not available"},
    },
)

SUPPORTED_MODELS: Dict[str, Dict[str, Any]] = {
    "tiny": {
        "name": "qwen/Qwen3-VL-2B-Instruct",
        "description": "轻量级模型（2B参数），适合边缘设备和资源受限环境",
        "params": "2B",
        "recommended": False,
        "memory_estimate": "~8GB",
    },
    "small": {
        "name": "qwen/Qwen3-VL-4B-Instruct",
        "description": "小型模型（4B参数），平衡速度和精度",
        "params": "4B",
        "recommended": False,
        "memory_estimate": "~12GB",
    },
    "medium": {
        "name": "qwen/Qwen3-VL-4B-Instruct",
        "description": "中型模型（4B参数），推荐用于大多数场景",
        "params": "4B",
        "recommended": True,
        "memory_estimate": "~12GB",
    },
    "large": {
        "name": "qwen/Qwen3-VL-8B-Instruct",
        "description": "大型模型（8B参数），高精度但需要更多资源",
        "params": "8B",
        "recommended": False,
        "memory_estimate": "~24GB",
    },
}

"""支持的视频分析任务类型。"""
SUPPORTED_TASKS: List[str] = ["recognize", "score", "moderate", "full"]


def create_video_routes(args: Any, api_key: Optional[str] = None):
    optional_api_key = get_api_key_dependency(api_key)

    async def _process_video_task(
        file_path: str, task: str, model_size: str = "medium", frame_interval: int = 10
    ):
        try:
            from bookroom_audio.models.qwen_vl import (
                is_qwen_vl_available,
                recognize_video,
                score_video,
                moderate_video,
                analyze_video_full,
                load_model_task,
            )

            if not is_qwen_vl_available():
                raise HTTPException(
                    status_code=503,
                    detail="Qwen3-VL is not available. Please install transformers package."
                )

            if task not in SUPPORTED_TASKS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid task '{task}'. Supported tasks: {', '.join(SUPPORTED_TASKS)}"
                )

            if model_size not in SUPPORTED_MODELS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid model size '{model_size}'. Supported sizes: {', '.join(SUPPORTED_MODELS.keys())}"
                )

            await load_model_task(args, {"model_size": model_size})

            if task == "recognize":
                result = await recognize_video(file_path, args, frame_interval)
            elif task == "score":
                result = await score_video(file_path, args, frame_interval)
            elif task == "moderate":
                result = await moderate_video(file_path, args, frame_interval)
            elif task == "full":
                result = await analyze_video_full(file_path, args, frame_interval)
            else:
                raise HTTPException(status_code=400, detail=f"Unknown task: {task}")

            return result

        except asyncio.CancelledError:
            logger.warning(f"Request cancelled during {task}")
            raise HTTPException(status_code=499, detail="Request cancelled")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error during {task}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    async def _save_upload_file(file: UploadFile) -> str:
        try:
            content = await file.read()
            original_filename = file.filename or "video.mp4"
            suffix = os.path.splitext(original_filename)[1] or ".mp4"

            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix
            ) as tmp_file:
                tmp_file.write(content)
                tmp_file_path = tmp_file.name

            return tmp_file_path

        except Exception as e:
            logger.error(f"Failed to save uploaded file: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail="Failed to process uploaded file"
            )

    @router.post(
        "/recognize",
        dependencies=[Depends(optional_api_key)],
        operation_id="recognize_video",
        summary="识别视频内容",
        description="""
识别视频中的视觉内容，包括物体、场景、人物动作等。

分析流程：
1. 从视频中提取关键帧（每隔 frame_interval 秒提取一帧）
2. 使用 Qwen3-VL 模型分析每一帧的视觉内容
3. 汇总所有帧的分析结果，生成视频内容摘要

返回结果包含：
- summary: 视频内容摘要
- objects: 识别到的物体列表
- scenes: 识别到的场景列表
- description: 详细描述文本
        """,
        responses={
            200: {
                "description": "识别成功",
                "content": {
                    "application/json": {
                        "example": {
                            "task": "recognize",
                            "total_frames_analyzed": 5,
                            "summary": "视频展示了一个城市街道的场景",
                            "objects": ["汽车", "行人", "建筑物"],
                            "scenes": ["城市街道", "交通路口"],
                            "description": "视频内容描述..."
                        }
                    }
                }
            }
        },
    )
    async def recognize_video_endpoint(
        file: UploadFile = File(
            ...,
            description="要分析的视频文件。支持 MP4, AVI, MOV 等常见格式"
        ),
        model: Optional[str] = "medium",
        frame_interval: Optional[int] = 10,
    ):
        """
        识别视频内容 - 描述视频中的视觉内容
        
        Args:
            file: 要分析的视频文件
            model: 模型大小 (tiny/small/medium/large)，默认 medium
            frame_interval: 帧提取间隔（秒），默认 10
        
        Returns:
            识别结果，包含摘要、物体列表、场景列表和详细描述
        """
        file_path = await _save_upload_file(file)
        return await _process_video_task(file_path, "recognize", model, frame_interval)

    @router.post(
        "/score",
        dependencies=[Depends(optional_api_key)],
        operation_id="score_video",
        summary="视频内容评分",
        description="""
对视频内容进行质量和适宜性评分。

评分维度：
- quality: 画质评分（清晰度、色彩、稳定性）
- content: 内容质量评分（主题明确度、信息量）
- interest: 趣味性评分（吸引力、观赏性）

评分范围：0-100分，越高表示质量越好。

返回结果包含各项评分的平均值和综合评分。
        """,
        responses={
            200: {
                "description": "评分成功",
                "content": {
                    "application/json": {
                        "example": {
                            "task": "score",
                            "total_frames_analyzed": 5,
                            "average_scores": {
                                "quality": 85.5,
                                "content": 78.2,
                                "interest": 82.0
                            },
                            "overall_score": 81.9,
                            "breakdown": {}
                        }
                    }
                }
            }
        },
    )
    async def score_video_endpoint(
        file: UploadFile = File(
            ...,
            description="要评分的视频文件。支持 MP4, AVI, MOV 等常见格式"
        ),
        model: Optional[str] = "medium",
        frame_interval: Optional[int] = 10,
    ):
        """
        视频内容评分 - 对视频内容进行质量和适宜性评分
        
        Args:
            file: 要评分的视频文件
            model: 模型大小，默认 medium
            frame_interval: 帧提取间隔（秒），默认 10
        
        Returns:
            评分结果，包含各项评分和综合评分
        """
        file_path = await _save_upload_file(file)
        return await _process_video_task(file_path, "score", model, frame_interval)

    @router.post(
        "/moderate",
        dependencies=[Depends(optional_api_key)],
        operation_id="moderate_video",
        summary="视频内容监测",
        description="""
检测视频中是否包含违规内容。

监测的违规类型：
- 色情内容 (pornography)
- 暴力内容 (violence)
- 恐怖内容 (terrorism)
- 非法物品 (illegal_items)
- 政治敏感 (political)
- 其他不当内容 (other)

返回结果包含：
- has_violations: 是否包含违规内容
- violation_count: 违规内容数量
- violation_types: 违规类型列表
- safe: 是否安全（无违规）
        """,
        responses={
            200: {
                "description": "监测成功",
                "content": {
                    "application/json": {
                        "example": {
                            "task": "moderate",
                            "total_frames_analyzed": 5,
                            "has_violations": False,
                            "violation_count": 0,
                            "violation_types": [],
                            "violations": [],
                            "safe": True
                        }
                    }
                }
            }
        },
    )
    async def moderate_video_endpoint(
        file: UploadFile = File(
            ...,
            description="要监测的视频文件。支持 MP4, AVI, MOV 等常见格式"
        ),
        model: Optional[str] = "medium",
        frame_interval: Optional[int] = 10,
    ):
        """
        视频内容监测 - 检测是否包含违规内容
        
        Args:
            file: 要监测的视频文件
            model: 模型大小，默认 medium
            frame_interval: 帧提取间隔（秒），默认 10
        
        Returns:
            监测结果，包含是否违规、违规数量和类型
        """
        file_path = await _save_upload_file(file)
        return await _process_video_task(file_path, "moderate", model, frame_interval)

    @router.post(
        "/analyze",
        dependencies=[Depends(optional_api_key)],
        operation_id="analyze_video",
        summary="完整视频分析",
        description="""
同时进行视频内容识别、评分和监测三项分析。

这是一个组合接口，相当于依次调用：
1. /recognize - 识别视频内容
2. /score - 视频内容评分
3. /moderate - 视频内容监测

适合需要一次性获取视频完整分析结果的场景。
        """,
        responses={
            200: {
                "description": "分析成功",
                "content": {
                    "application/json": {
                        "example": {
                            "task": "full",
                            "recognize": {
                                "task": "recognize",
                                "total_frames_analyzed": 5,
                                "summary": "视频内容摘要",
                                "objects": [],
                                "scenes": [],
                                "description": "..."
                            },
                            "score": {
                                "task": "score",
                                "total_frames_analyzed": 5,
                                "average_scores": {},
                                "overall_score": 80.0,
                                "breakdown": {}
                            },
                            "moderate": {
                                "task": "moderate",
                                "total_frames_analyzed": 5,
                                "has_violations": False,
                                "violation_count": 0,
                                "violation_types": [],
                                "violations": [],
                                "safe": True
                            }
                        }
                    }
                }
            }
        },
    )
    async def analyze_video_endpoint(
        file: UploadFile = File(
            ...,
            description="要分析的视频文件。支持 MP4, AVI, MOV 等常见格式"
        ),
        model: Optional[str] = "medium",
        frame_interval: Optional[int] = 10,
    ):
        """
        完整分析视频 - 同时进行识别、评分和监测
        
        Args:
            file: 要分析的视频文件
            model: 模型大小，默认 medium
            frame_interval: 帧提取间隔（秒），默认 10
        
        Returns:
            完整分析结果，包含识别、评分和监测三项结果
        """
        file_path = await _save_upload_file(file)
        return await _process_video_task(file_path, "full", model, frame_interval)

    @router.get(
        "/models",
        dependencies=[Depends(optional_api_key)],
        operation_id="list_vl_models",
        summary="获取支持的VL模型列表",
        description="""
获取所有支持的 Qwen3-VL 模型列表，包含模型名称、描述、参数规模和推荐配置。

返回结果包含：
- models: 所有支持的模型信息
- recommendations: 针对不同场景的模型推荐
- notes: 使用注意事项
        """,
        responses={
            200: {
                "description": "成功获取模型列表",
                "content": {
                    "application/json": {
                        "example": {
                            "models": {
                                "tiny": {
                                    "name": "qwen/Qwen3-VL-2B-Instruct",
                                    "description": "轻量级模型（2B参数）",
                                    "params": "2B",
                                    "recommended": False,
                                    "memory_estimate": "~8GB"
                                },
                                "medium": {
                                    "name": "qwen/Qwen3-VL-4B-Instruct",
                                    "description": "中型模型（4B参数）",
                                    "params": "4B",
                                    "recommended": True,
                                    "memory_estimate": "~12GB"
                                }
                            },
                            "recommendations": {
                                "edge_device": "tiny",
                                "balanced": "medium",
                                "high_accuracy": "large"
                            },
                            "notes": "模型首次使用时会自动下载，建议在网络良好的环境下使用"
                        }
                    }
                }
            }
        },
    )
    async def list_vl_models():
        """
        获取支持的 Qwen3-VL 模型列表
        
        Returns:
            模型列表和推荐配置
        """
        return {
            "models": SUPPORTED_MODELS,
            "recommendations": {
                "edge_device": "tiny",
                "balanced": "medium",
                "high_accuracy": "large",
            },
            "notes": "模型首次使用时会自动下载，建议在网络良好的环境下使用。大型模型需要更多内存。"
        }

    @router.get(
        "/tasks",
        dependencies=[Depends(optional_api_key)],
        operation_id="list_vl_tasks",
        summary="获取支持的任务类型",
        description="""
获取所有支持的视频分析任务类型及其详细描述。

支持的任务类型：
- recognize: 识别视频内容
- score: 视频内容评分
- moderate: 视频内容监测
- full: 完整分析（同时执行以上三项）
        """,
        responses={
            200: {
                "description": "成功获取任务列表",
                "content": {
                    "application/json": {
                        "example": {
                            "tasks": ["recognize", "score", "moderate", "full"],
                            "task_descriptions": {
                                "recognize": "识别视频内容 - 描述视频中的视觉内容",
                                "score": "视频内容评分 - 对视频内容进行质量和适宜性评分",
                                "moderate": "视频内容监测 - 检测是否包含违规内容",
                                "full": "完整分析 - 同时进行识别、评分和监测"
                            },
                            "endpoints": {
                                "recognize": "POST /v1/video/recognize",
                                "score": "POST /v1/video/score",
                                "moderate": "POST /v1/video/moderate",
                                "full": "POST /v1/video/analyze"
                            }
                        }
                    }
                }
            }
        },
    )
    async def list_vl_tasks():
        """
        获取支持的视频分析任务类型
        
        Returns:
            任务列表和详细描述
        """
        return {
            "tasks": SUPPORTED_TASKS,
            "task_descriptions": {
                "recognize": "识别视频内容 - 描述视频中的视觉内容，包括物体、场景、人物动作等",
                "score": "视频内容评分 - 对视频内容进行质量和适宜性评分（画质、内容、趣味性）",
                "moderate": "视频内容监测 - 检测是否包含违规内容（色情、暴力、恐怖、非法物品等）",
                "full": "完整分析 - 同时进行识别、评分和监测，适合一次性获取完整结果",
            },
            "endpoints": {
                "recognize": "POST /v1/video/recognize",
                "score": "POST /v1/video/score",
                "moderate": "POST /v1/video/moderate",
                "full": "POST /v1/video/analyze",
            }
        }

    @router.get(
        "/status",
        dependencies=[Depends(optional_api_key)],
        operation_id="get_vl_status",
        summary="获取VL模型状态",
        description="""
获取 Qwen3-VL 模型的当前状态，包括是否可用、是否已加载、当前模型等信息。

返回状态：
- available: VL功能是否可用
- model_loaded: 模型是否已加载到内存
- current_model: 当前加载的模型名称
- supported_models: 支持的模型列表
- supported_tasks: 支持的任务列表
- device: 当前使用的设备（CPU/GPU）
        """,
        responses={
            200: {
                "description": "成功获取状态",
                "content": {
                    "application/json": {
                        "example": {
                            "available": True,
                            "model_loaded": True,
                            "current_model": "qwen/Qwen3-VL-4B-Instruct",
                            "supported_models": ["tiny", "small", "medium", "large"],
                            "supported_tasks": ["recognize", "score", "moderate", "full"],
                            "device": "cpu"
                        }
                    }
                }
            }
        },
    )
    async def get_vl_status():
        """
        获取 Qwen3-VL 模型状态
        
        Returns:
            VL模型的当前状态信息
        """
        try:
            from bookroom_audio.models.qwen_vl import get_qwen_vl_status
            return get_qwen_vl_status()
        except ImportError:
            return {
                "available": False,
                "model_loaded": False,
                "error": "transformers package not installed"
            }

    return router