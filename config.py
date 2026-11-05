"""
Configuration management for Grocery Agent.

Supports three configuration sources (in priority order):
1. Environment variables (highest priority)
2. .env file (if exists)
3. Built-in defaults (lowest priority)

Usage:
    from config import config
    model_path = config.MODEL_PATH
"""

import os
import logging
from pathlib import Path

# Try to load from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use env vars only


class Config:
    """Base configuration with sensible defaults."""
    
    # ============ LLM Settings ============
    # MLX loads local model directories, not individual GGUF files.
    MODEL_PATH = os.getenv("MODEL_PATH", "./models/llama-3-8b-instruct-mlx")
    LLM_N_CTX = int(os.getenv("LLM_N_CTX", "2048"))
    LLM_N_THREADS = int(os.getenv("LLM_N_THREADS", "4"))
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))

    # ============ Meal Plan Rules ============
    # Keep MAX_INGREDIENTS_PER_MEAL in sync with rule 5 of the system prompt in agent.py.
    MAX_INGREDIENTS_PER_MEAL = int(os.getenv("MAX_INGREDIENTS_PER_MEAL", "7"))
    # How many times the agent sends an invalid meal plan back to the model for correction.
    MAX_REPAIR_ATTEMPTS = int(os.getenv("MAX_REPAIR_ATTEMPTS", "2"))
    
    # ============ Data Storage Settings ============
    PANTRY_FILE = os.getenv("PANTRY_FILE", "data/pantry.json")
    MEMORY_FILE = os.getenv("MEMORY_FILE", "memory/conversation.json")
    
    # ============ Logging Settings ============
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # ============ Application Settings ============
    APP_NAME = "Grocery Agent"
    APP_VERSION = "1.0.0"
    
    @classmethod
    def validate(cls) -> bool:
        """Validate the local MLX model directory."""
        model_path = Path(os.path.expanduser(cls.MODEL_PATH))
        if not model_path.is_dir():
            raise FileNotFoundError(
                f"MLX model directory not found: {model_path}. "
                "Convert or download an MLX model into this directory."
            )
        if not (model_path / "config.json").is_file():
            raise FileNotFoundError(f"Missing MLX model config: {model_path / 'config.json'}")
        if not list(model_path.glob("model*.safetensors")):
            raise FileNotFoundError(f"Missing MLX safetensors weights in: {model_path}")
        
        # Ensure directories exist
        Path("data").mkdir(exist_ok=True)
        Path("memory").mkdir(exist_ok=True)
        
        return True
    
    @classmethod
    def to_dict(cls) -> dict:
        """Return config as dictionary (for logging/debugging)."""
        return {
            k: v for k, v in cls.__dict__.items()
            if not k.startswith("_") and k.isupper()
        }


class DevelopmentConfig(Config):
    """Development configuration with verbose logging."""
    LOG_LEVEL = "DEBUG"


class ProductionConfig(Config):
    """Production configuration with minimal logging."""
    LOG_LEVEL = "INFO"


class TestingConfig(Config):
    """Testing configuration with small/fast model."""
    MODEL_PATH = os.getenv("MODEL_PATH", "mlx-community/Llama-3-8B-Instruct-4bit")
    LLM_N_THREADS = 2
    LLM_MAX_TOKENS = 256
    LOG_LEVEL = "DEBUG"


def get_config() -> Config:
    """
    Get appropriate configuration based on environment.
    
    Environment variable: ENV
    - "production" → ProductionConfig
    - "testing" → TestingConfig
    - default → DevelopmentConfig
    """
    env = os.getenv("ENV", "development").lower()
    
    configs = {
        "production": ProductionConfig,
        "prod": ProductionConfig,
        "testing": TestingConfig,
        "test": TestingConfig,
        "development": DevelopmentConfig,
        "dev": DevelopmentConfig,
    }
    
    config_class = configs.get(env, DevelopmentConfig)
    return config_class()


# Default config instance
config = get_config()

# Setup logging with config
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT
)

logger = logging.getLogger(__name__)
logger.debug(f"Loaded {config.__class__.__name__} configuration")
logger.debug(f"Model: {config.MODEL_PATH}")
logger.debug(f"Log level: {config.LOG_LEVEL}")
