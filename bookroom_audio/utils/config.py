"""
统一配置管理模块
统一管理服务器、模型、下载缓存等所有配置参数
"""

import os
from typing import Optional
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerConfig:
    """服务器配置"""
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 15231
    workers: int = 1
    api_key: Optional[str] = None
    reload: bool = False
    ssl: bool = False
    ssl_certfile: Optional[str] = None
    ssl_keyfile: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> 'ServerConfig':
        """从环境变量创建配置"""
        return cls(
            debug=str(os.getenv("SERVER_DEBUG", "False")).lower() == "true",
            host=os.getenv("SERVER_HOST", "0.0.0.0"),
            port=int(os.getenv("SERVER_PORT", "15231")),
            workers=int(os.getenv("SERVER_WORKERS", "1")),
            api_key=os.getenv("API_KEY", None),
            reload=str(os.getenv("SERVER_RELOAD", "False")).lower() == "true",
            ssl=str(os.getenv("SERVER_SSL", "False")).lower() == "true",
            ssl_certfile=os.getenv("SERVER_SSL_CERTFILE", None),
            ssl_keyfile=os.getenv("SERVER_SSL_KEYFILE", None),
        )


@dataclass
class ModelConfig:
    """模型配置"""
    # ASR 配置
    asr_engine: str = "qwen-asr"
    asr_model: str = "medium"
    asr_language: str = "zh"
    
    # TTS 配置
    tts_engine: str = "chattts"
    tts_language: str = "zh"
    
    # 通用配置
    device: str = "cpu"
    compute_type: str = "int8"
    model_keep_alive: str = "5m"
    num_workers: int = 1
    
    # 兼容性：保持旧的engine参数
    @property
    def engine(self) -> str:
        """返回ASR引擎（兼容旧代码）"""
        return self.asr_engine
    
    @property
    def model(self) -> str:
        """返回ASR模型（兼容旧代码）"""
        return self.asr_model
    
    @property
    def language(self) -> str:
        """返回ASR语言（兼容旧代码）"""
        return self.asr_language
    
    @classmethod
    def from_env(cls) -> 'ModelConfig':
        """从环境变量创建配置"""
        return cls(
            # ASR 配置
            asr_engine=os.getenv("ASR_ENGINE", "qwen-asr"),
            asr_model=os.getenv("ASR_MODEL", "medium"),
            asr_language=os.getenv("ASR_LANGUAGE", "zh"),
            
            # TTS 配置
            tts_engine=os.getenv("TTS_ENGINE", "chattts"),
            tts_language=os.getenv("TTS_LANGUAGE", "zh"),
            
            # 通用配置
            device=os.getenv("DEVICE", "cpu"),
            compute_type=os.getenv("COMPUTE_TYPE", "int8"),
            model_keep_alive=os.getenv("MODEL_KEEP_ALIVE", "5m"),
            num_workers=int(os.getenv("NUM_WORKERS", "1")),
        )


@dataclass
class CacheConfig:
    """缓存和下载配置"""
    # 统一的缓存目录
    cache_dir: str = "./.cache"
    
    # 离线模式配置
    local_files_only: bool = True
    transformers_offline: bool = True
    hf_datasets_offline: bool = True
    
    # Hugging Face 配置
    hf_endpoint: Optional[str] = None
    hf_token: Optional[str] = None
    
    # 模型源配置
    model_source: str = "huggingface"  # huggingface, modelscope, local
    
    @classmethod
    def from_env(cls) -> 'CacheConfig':
        """从环境变量创建配置"""
        # 统一缓存目录：优先使用 CACHE_DIR，其次 DOWNLOAD_ROOT，最后默认值
        cache_dir = (
            os.getenv("CACHE_DIR") or 
            os.getenv("TRANSFORMERS_CACHE") or 
            os.getenv("DOWNLOAD_ROOT") or 
            "./.cache"
        )
        
        # 统一离线模式配置
        local_files_only = str(os.getenv("LOCAL_FILES_ONLY", "True")).lower() == "true"
        transformers_offline = str(os.getenv("TRANSFORMERS_OFFLINE", "True")).lower() == "true"
        hf_datasets_offline = str(os.getenv("HF_DATASETS_OFFLINE", "True")).lower() == "true"
        
        # 如果任一离线参数为 true，则所有离线参数都设为 true
        if local_files_only or transformers_offline or hf_datasets_offline:
            local_files_only = True
            transformers_offline = True
            hf_datasets_offline = True
        
        return cls(
            cache_dir=cache_dir,
            local_files_only=local_files_only,
            transformers_offline=transformers_offline,
            hf_datasets_offline=hf_datasets_offline,
            hf_endpoint=os.getenv("HF_ENDPOINT", None),
            hf_token=os.getenv("HF_TOKEN", None),
            model_source=os.getenv("MODEL_SOURCE", "huggingface"),
        )
    
    def setup_environment(self):
        """设置环境变量，确保所有组件使用统一的配置"""
        # 确保缓存目录不为空
        if not self.cache_dir:
            self.cache_dir = "./.cache"
        
        # 设置统一的缓存目录
        os.environ["TRANSFORMERS_CACHE"] = self.cache_dir
        os.environ["HF_HOME"] = self.cache_dir
        os.environ["HUGGINGFACE_HUB_CACHE"] = self.cache_dir
        
        # 设置离线模式
        if self.transformers_offline:
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_HUB_OFFLINE"] = "1"  # 关键：设置HF Hub离线模式
        if self.hf_datasets_offline:
            os.environ["HF_DATASETS_OFFLINE"] = "1"
        
        # 设置 Hugging Face 端点
        if self.hf_endpoint:
            os.environ["HF_ENDPOINT"] = self.hf_endpoint
        
        # 设置 Hugging Face Token
        if self.hf_token:
            os.environ["HF_TOKEN"] = self.hf_token
    
    def get_model_kwargs(self) -> dict:
        """获取模型加载时的 kwargs"""
        kwargs = {
            "cache_dir": self.cache_dir,
            "local_files_only": self.local_files_only,
        }
        
        # 如果有 Hugging Face token，添加到 kwargs
        if self.hf_token:
            kwargs["token"] = self.hf_token
        
        return kwargs


@dataclass
class AppConfig:
    """应用总配置"""
    server: ServerConfig = field(default_factory=ServerConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    
    @classmethod
    def from_env(cls) -> 'AppConfig':
        """从环境变量创建配置"""
        config = cls(
            server=ServerConfig.from_env(),
            model=ModelConfig.from_env(),
            cache=CacheConfig.from_env(),
        )
        
        # 设置环境变量
        config.cache.setup_environment()
        
        # 设置全局配置实例
        global app_config
        app_config = config
        
        return config
    
    def update_from_args(self, args):
        """从命令行参数更新配置"""
        # 更新服务器配置
        if args.key is not None:
            self.server.api_key = args.key
        if args.debug is not None:
            self.server.debug = args.debug
        if args.host is not None:
            self.server.host = args.host
        if args.port is not None:
            self.server.port = args.port
        if args.workers is not None:
            self.server.workers = args.workers
        if args.reload:
            self.server.reload = True
        if args.ssl is not None:
            self.server.ssl = args.ssl
        if args.ssl_certfile is not None:
            self.server.ssl_certfile = args.ssl_certfile
        if args.ssl_keyfile is not None:
            self.server.ssl_keyfile = args.ssl_keyfile
        
        # 更新模型配置
        if args.engine is not None:
            self.model.asr_engine = args.engine
        if args.model is not None:
            self.model.asr_model = args.model
        if args.language is not None:
            self.model.asr_language = args.language
        if args.device is not None:
            self.model.device = args.device
        if args.compute_type is not None:
            self.model.compute_type = args.compute_type
        if args.model_keep_alive is not None:
            self.model.model_keep_alive = args.model_keep_alive
        if args.num_workers is not None:
            self.model.num_workers = args.num_workers
        
        # 更新缓存配置
        if args.download_root is not None:
            self.cache.cache_dir = args.download_root
        if args.local_files_only is not None:
            self.cache.local_files_only = args.local_files_only
            # 同步更新其他离线模式配置
            if self.cache.local_files_only:
                self.cache.transformers_offline = True
                self.cache.hf_datasets_offline = True
            else:
                self.cache.transformers_offline = False
                self.cache.hf_datasets_offline = False
        
        # 重新设置环境变量
        self.cache.setup_environment()


# 全局配置实例
app_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """获取全局配置实例"""
    global app_config
    if app_config is None:
        app_config = AppConfig.from_env()
    return app_config


def reset_config():
    """重置全局配置"""
    global app_config
    app_config = None


def print_config_summary():
    """打印配置摘要"""
    # 直接获取全局配置，不创建新实例
    global app_config
    if app_config is None:
        # 如果配置未初始化，不打印任何内容
        return
    
    config = app_config
    
    print("\n" + "="*60)
    print("📋 应用配置摘要")
    print("="*60)
    
    print("\n🖥️  服务器配置:")
    print(f"  - Host: {config.server.host}")
    print(f"  - Port: {config.server.port}")
    print(f"  - Workers: {config.server.workers}")
    print(f"  - Debug: {config.server.debug}")
    print(f"  - API Key: {'已设置' if config.server.api_key else '未设置'}")
    
    print("\n🤖 模型配置:")
    print(f"  - ASR Engine: {config.model.asr_engine}")
    print(f"  - ASR Model: {config.model.asr_model}")
    print(f"  - ASR Language: {config.model.asr_language}")
    print(f"  - TTS Engine: {config.model.tts_engine}")
    print(f"  - TTS Language: {config.model.tts_language}")
    print(f"  - Device: {config.model.device}")
    print(f"  - Compute Type: {config.model.compute_type}")
    print(f"  - Model Keep Alive: {config.model.model_keep_alive}")
    
    print("\n💾 缓存配置:")
    print(f"  - Cache Dir: {config.cache.cache_dir}")
    print(f"  - Local Files Only: {config.cache.local_files_only}")
    print(f"  - Transformers Offline: {config.cache.transformers_offline}")
    print(f"  - HF Datasets Offline: {config.cache.hf_datasets_offline}")
    print(f"  - HF Endpoint: {config.cache.hf_endpoint or '默认'}")
    print(f"  - Model Source: {config.cache.model_source}")
    
    print("\n" + "="*60 + "\n")