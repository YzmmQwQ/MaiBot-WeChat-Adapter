"""
maim_message 通信层
负责与 MaiBot 核心的 WebSocket 通信
"""
import importlib.metadata
from typing import Dict, Any

from maim_message import Router, RouteConfig, TargetConfig, MessageBase
from maim_message.client import create_client_config, WebSocketClient
from maim_message.message import APIMessageBase

from src.config.config_manager import global_config
from src.logger import logger, custom_logger
from src.send_handler.main_send_handler import send_handler


# 检查 maim_message 版本是否支持 MessageConverter (>= 0.6.2)
try:
    maim_message_version = importlib.metadata.version("maim_message")
    version_int = [int(x) for x in maim_message_version.split(".")]
    HAS_MESSAGE_CONVERTER = version_int >= [0, 6, 2]
except (importlib.metadata.PackageNotFoundError, ValueError):
    HAS_MESSAGE_CONVERTER = False

# 全局 router 实例
router = None


class APIServerWrapper:
    """
    WebSocketClient 包装器，使其兼容旧版 Router 接口
    """

    def __init__(self, client: WebSocketClient):
        self.client = client
        self.platform = global_config.maibot_server.platform_name

    async def send_message(self, message: MessageBase) -> bool:
        """发送消息到 MaiBot"""
        from maim_message import MessageConverter

        api_message = MessageConverter.to_api_receive(
            message=message,
            api_key=global_config.maibot_server.api_key,
            platform=message.message_info.platform or self.platform,
        )
        return await self.client.send_message(api_message)

    async def send_custom_message(
        self, platform: str, message_type_name: str, message: Dict
    ) -> bool:
        """发送自定义消息"""
        return await self.client.send_custom_message(message_type_name, message)

    async def run(self):
        """启动客户端"""
        await self.client.start()
        await self.client.connect()

    async def stop(self):
        """停止客户端"""
        await self.client.stop()


async def _on_message_bridge(message: APIMessageBase, metadata: Dict[str, Any]):
    """消息桥接回调，将 API 消息转换为旧版格式"""
    try:
        from maim_message import MessageConverter

        legacy_message = MessageConverter.from_api_send(message)
        msg_dict = legacy_message.to_dict()

        await send_handler.handle_message(msg_dict)

    except Exception as e:
        logger.error(f"消息桥接转换失败: {e}")
        import traceback
        logger.error(traceback.format_exc())


async def mmc_start_com():
    """启动 maim_message 通信"""
    global router
    config = global_config.maibot_server

    if config.enable_api_server and HAS_MESSAGE_CONVERTER:
        logger.info("使用 API-Server 模式连接 MaiBot")

        client_config = create_client_config(
            url=config.base_url,
            api_key=config.api_key,
            platform=config.platform_name,
            on_message=_on_message_bridge,
            custom_logger=custom_logger,
        )

        client = WebSocketClient(client_config)
        router = APIServerWrapper(client)
        await router.run()

    else:
        logger.info("使用 Legacy WebSocket 模式连接 MaiBot")

        route_config = RouteConfig(
            route_config={
                config.platform_name: TargetConfig(
                    url=f"ws://{config.host}:{config.port}/ws",
                    token=None,
                )
            }
        )

        router = Router(route_config, custom_logger)
        router.register_class_handler(send_handler.handle_message)
        await router.run()


async def mmc_stop_com():
    """停止 maim_message 通信"""
    if router:
        await router.stop()
