"""配置管理模块"""
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import tomllib
import tomli_w

from src.config.config_base import Config


class ConfigManager:
    """配置管理器"""

    _instance: Optional['ConfigManager'] = None
    _lock = threading.Lock()

    def __new__(cls, config_path: str = "config.toml"):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: str = "config.toml"):
        if self._initialized:
            return
        self._initialized = True
        self.config_path = Path(config_path)
        self._config: Optional[Config] = None
        self._callbacks: Dict[str, list] = {}
        self._stop_event = threading.Event()

    def load(self) -> Config:
        """加载配置文件"""
        if not self.config_path.exists():
            self._config = Config()
            self.save()
            return self._config

        with open(self.config_path, "rb") as f:
            data = tomllib.load(f)

        self._config = Config.from_dict(data)
        return self._config

    def save(self) -> None:
        """保存配置到文件"""
        if self._config is None:
            return

        data = {
            "debug": {"level": self._config.debug.level},
            "maibot_server": {
                "enable_api_server": self._config.maibot_server.enable_api_server,
                "base_url": self._config.maibot_server.base_url,
                "api_key": self._config.maibot_server.api_key,
                "platform_name": self._config.maibot_server.platform_name,
                "host": self._config.maibot_server.host,
                "port": self._config.maibot_server.port,
            },
            "wechat": {
                "base_url": self._config.wechat.base_url,
                "cdn_base_url": self._config.wechat.cdn_base_url,
                "bot_type": self._config.wechat.bot_type,
                "token": self._config.wechat.token,
                "account_id": self._config.wechat.account_id,
                "qr_poll_interval": self._config.wechat.qr_poll_interval,
                "long_poll_timeout_ms": self._config.wechat.long_poll_timeout_ms,
                "api_timeout_ms": self._config.wechat.api_timeout_ms,
            },
            "chat": {
                "private_list_type": self._config.chat.private_list_type,
                "private_list": self._config.chat.private_list,
                "ban_user_id": self._config.chat.ban_user_id,
            },
        }

        with open(self.config_path, "wb") as f:
            tomli_w.dump(data, f)

    async def start_watch(self) -> None:
        """启动配置文件监控"""
        import asyncio
        last_mtime = 0
        while not self._stop_event.is_set():
            try:
                if self.config_path.exists():
                    current_mtime = self.config_path.stat().st_mtime
                    if current_mtime != last_mtime:
                        last_mtime = current_mtime
                        self.load()
            except Exception:
                pass
            await asyncio.sleep(1)

    def stop_watch(self) -> None:
        """停止配置文件监控"""
        self._stop_event.set()

    @property
    def config(self) -> Config:
        """获取当前配置"""
        if self._config is None:
            self.load()
        return self._config


# 全局实例（延迟初始化）
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config() -> Config:
    """获取配置"""
    return get_config_manager().load()


# 导出全局配置对象
global_config = get_config()
config_manager = get_config_manager()
