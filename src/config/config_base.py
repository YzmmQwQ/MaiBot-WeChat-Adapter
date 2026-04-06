from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path


@dataclass
class DebugConfig:
    """调试配置"""
    level: str = "INFO"


@dataclass
class MaiBotServerConfig:
    """MaiBot 服务器配置"""
    # API-Server 模式配置
    enable_api_server: bool = True
    base_url: str = "ws://127.0.0.1:8080/ws"
    api_key: str = ""
    platform_name: str = "wechat"

    # Legacy 模式配置 (备用)
    host: str = "127.0.0.1"
    port: int = 8099


@dataclass
class WeChatConfig:
    """微信配置"""
    base_url: str = "https://ilinkai.weixin.qq.com"
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    bot_type: str = "3"
    token: str = ""  # 登录后自动获取，也可手动填写
    account_id: str = ""  # 登录后自动获取

    # 轮询配置
    qr_poll_interval: int = 1  # 二维码状态轮询间隔(秒)
    long_poll_timeout_ms: int = 35000  # 消息拉取超时(毫秒)
    api_timeout_ms: int = 15000  # API 请求超时(毫秒)


@dataclass
class ChatConfig:
    """聊天控制配置"""
    private_list_type: str = "none"  # none, whitelist, blacklist
    private_list: List[int] = field(default_factory=list)
    ban_user_id: List[int] = field(default_factory=list)


@dataclass
class Config:
    """全局配置"""
    debug: DebugConfig = field(default_factory=DebugConfig)
    maibot_server: MaiBotServerConfig = field(default_factory=MaiBotServerConfig)
    wechat: WeChatConfig = field(default_factory=WeChatConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """从字典创建配置"""
        config = cls()

        if "debug" in data:
            config.debug = DebugConfig(**data["debug"])

        if "maibot_server" in data:
            ms_data = data["maibot_server"]
            config.maibot_server = MaiBotServerConfig(**ms_data)

        if "wechat" in data:
            wc_data = data["wechat"]
            config.wechat = WeChatConfig(**wc_data)

        if "chat" in data:
            chat_data = data["chat"]
            config.chat = ChatConfig(**chat_data)

        return config
