"""
图片分析 API 路由模块。

提供基于 Qwen3-VL 模型的图片内容分析功能，包括：
- 图片内容识别（recognize）：描述图片中的视觉内容
- 图片内容评分（score）：对图片内容进行质量和适宜性评分
- 图片内容监测（moderate）：检测是否包含违规内容

API 端点:
- POST /v1/image/recognize - 识别图片内容
- POST /v1/image/score - 图片内容评分
- POST /v1/image/moderate - 图片内容监测
- GET /v1/image/models - 获取支持的模型列表
- GET /v1/image/status - 获取 VL 模型状态

支持的图片格式：JPEG, PNG, GIF, BMP 等常见格式
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

SUPPORTED_TASKS: List[str] = ["recognize", "score", "moderate"]
SUPPORTED_FORMATS = ["jpg", "jpeg", "png", "gif", "bmp", "webp"]


def create_image_routes(args: Any, api_key: Optional[str] = None):
    router = APIRouter(
        prefix="/v1/image",
        tags=["image"],
        responses={
            400: {"description": "Invalid request parameters"},
            401: {"description": "Unauthorized - Invalid API key"},
            500: {"description": "Internal server error"},
            503: {"description": "Service unavailable - VL model not available"},
        },
    )

    optional_api_key = get_api_key_dependency(api_key)

    async def _save_upload_file(file: UploadFile) -> str:
        """保存上传的文件到临时目录"""
        try:
            content = await file.read()
            original_filename = file.filename or "image.jpg"
            suffix = os.path.splitext(original_filename)[1] or ".jpg"
            
            ext = suffix.lower()[1:] if suffix.startswith('.') else suffix.lower()
            if ext not in SUPPORTED_FORMATS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported image format: {ext}. Supported formats: {SUPPORTED_FORMATS}"
                )

            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix
            ) as tmp_file:
                tmp_file.write(content)
                tmp_file_path = tmp_file.name

            return tmp_file_path

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to save uploaded file: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail="Failed to process uploaded file"
            )

    async def _process_image_task(file_path: str, task_type: str, model: str):
        """处理图片分析任务"""
        try:
            from bookroom_audio.models.qwen_vl import (
                recognize_image,
                score_image,
                moderate_image,
                load_model_task,
            )

            from dataclasses import dataclass, field

            @dataclass
            class MockModelConfig:
                device: str = "cpu"
                vl_model: str = model

            @dataclass
            class MockArgs:
                model: MockModelConfig = field(default_factory=MockModelConfig)

            await load_model_task(MockArgs(), {"model_size": model})

            if task_type == "recognize":
                result = await recognize_image(file_path, MockArgs())
            elif task_type == "score":
                result = await score_image(file_path, MockArgs())
            elif task_type == "moderate":
                result = await moderate_image(file_path, MockArgs())
            else:
                raise HTTPException(status_code=400, detail=f"Unknown task: {task_type}")

            return result

        except ImportError as e:
            logger.error(f"VL module import error: {e}", exc_info=True)
            raise HTTPException(
                status_code=503, detail="VL model not available"
            )
        except Exception as e:
            logger.error(f"Image processing error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/recognize",
        dependencies=[Depends(optional_api_key)],
        operation_id="image_recognize",
        summary="识别图片内容",
        description="""
识别图片中的视觉内容，包括物体、场景、人物动作等。

分析流程：
1. 接收上传的图片文件
2. 使用 Qwen3-VL 模型分析图片内容
3. 返回图片内容描述

支持的图片格式：JPEG, PNG, GIF, BMP, WebP

返回结果包含：
- summary: 图片内容摘要
- description: 详细描述文本
- objects: 识别到的物体列表
- scenes: 识别到的场景列表
        """,
        responses={
            200: {
                "description": "识别成功",
                "content": {
                    "application/json": {
                        "example": {
                            "task": "recognize",
                            "summary": "一只可爱的猫咪坐在沙发上",
                            "objects": ["猫", "沙发", "窗户"],
                            "scenes": ["室内", "客厅"],
                            "description": "图片展示了一只橘色猫咪舒适地坐在灰色沙发上..."
                        }
                    }
                }
            }
        },
    )
    async def recognize_image_endpoint(
        file: UploadFile = File(
            ...,
            description="要分析的图片文件。支持 JPEG, PNG, GIF, BMP, WebP 等格式"
        ),
        model: Optional[str] = "medium",
    ):
        file_path = await _save_upload_file(file)
        try:
            return await _process_image_task(file_path, "recognize", model)
        finally:
            os.remove(file_path)

    @router.post(
        "/score",
        dependencies=[Depends(optional_api_key)],
        operation_id="image_score",
        summary="图片内容评分",
        description="""
对图片内容进行质量和适宜性评分。

评分维度：
- quality_score: 质量分数（清晰度、构图、色彩）
- appropriateness_score: 适宜性分数（是否适合全年龄段）
- value_score: 价值分数（信息价值、艺术价值）
- overall_score: 综合分数

评分范围：0-10分，越高表示质量越好。

支持的图片格式：JPEG, PNG, GIF, BMP, WebP
        """,
        responses={
            200: {
                "description": "评分成功",
                "content": {
                    "application/json": {
                        "example": {
                            "task": "score",
                            "quality_score": 8.5,
                            "appropriateness_score": 9.0,
                            "value_score": 7.5,
                            "overall_score": 8.3,
                            "explanation": "图片质量良好，内容适宜全年龄段观看"
                        }
                    }
                }
            }
        },
    )
    async def score_image_endpoint(
        file: UploadFile = File(
            ...,
            description="要评分的图片文件。支持 JPEG, PNG, GIF, BMP, WebP 等格式"
        ),
        model: Optional[str] = "medium",
    ):
        file_path = await _save_upload_file(file)
        try:
            return await _process_image_task(file_path, "score", model)
        finally:
            os.remove(file_path)

    @router.post(
        "/moderate",
        dependencies=[Depends(optional_api_key)],
        operation_id="image_moderate",
        summary="图片内容监测",
        description="""
检测图片中是否包含违规内容。

监测的违规类型：
- 色情内容 (pornography)
- 暴力内容 (violence)
- 恐怖内容 (terrorism)
- 非法物品 (illegal_items)
- 政治敏感 (political)
- 其他不当内容 (other)

支持的图片格式：JPEG, PNG, GIF, BMP, WebP

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
    async def moderate_image_endpoint(
        file: UploadFile = File(
            ...,
            description="要监测的图片文件。支持 JPEG, PNG, GIF, BMP, WebP 等格式"
        ),
        model: Optional[str] = "medium",
    ):
        file_path = await _save_upload_file(file)
        try:
            return await _process_image_task(file_path, "moderate", model)
        finally:
            os.remove(file_path)

    @router.get(
        "/models",
        dependencies=[Depends(optional_api_key)],
        operation_id="image_list_models",
        summary="获取支持的VL模型列表",
        description="获取所有支持的 Qwen3-VL 模型列表，用于图片分析。",
    )
    async def list_image_models():
        return {
            "models": SUPPORTED_MODELS,
            "recommendations": {
                "edge_device": "tiny",
                "balanced": "medium",
                "high_accuracy": "large",
            },
            "notes": "模型首次使用时会自动下载，建议在网络良好的环境下使用。"
        }

    @router.get(
        "/status",
        dependencies=[Depends(optional_api_key)],
        operation_id="image_get_status",
        summary="获取图片分析状态",
        description="获取图片分析功能的当前状态。",
    )
    async def get_image_status():
        try:
            from bookroom_audio.models.qwen_vl import get_qwen_vl_status
            result = get_qwen_vl_status()
            result["supported_tasks"] = SUPPORTED_TASKS
            result["supported_formats"] = SUPPORTED_FORMATS
            return result
        except ImportError:
            return {
                "available": False,
                "model_loaded": False,
                "error": "transformers package not installed"
            }

    return router