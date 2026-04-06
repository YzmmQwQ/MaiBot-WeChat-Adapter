"""
微信消息接收处理
将微信消息转换为 maim_message 格式并发送给 MaiBot
"""
import time
import base64
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, cast
from dataclasses import dataclass, field

from maim_message import (
    UserInfo,
    GroupInfo,
    Seg,
    BaseMessageInfo,
    MessageBase,
    FormatInfo,
)

from src.logger import logger
from src.config.config_manager import global_config
from src.weixin_client import WeixinClient


@dataclass
class UserContext:
    """用户上下文，存储 context_token 等"""
    context_token: str = ""
    last_active: float = 0.0


class MessageHandler:
    """微信消息处理器"""

    # 消息类型常量
    TEXT_ITEM_TYPE = 1
    IMAGE_ITEM_TYPE = 2
    VOICE_ITEM_TYPE = 3
    FILE_ITEM_TYPE = 4
    VIDEO_ITEM_TYPE = 5

    def __init__(self):
        self.client: Optional[WeixinClient] = None
        self._user_contexts: Dict[str, UserContext] = {}
        self._temp_dir = Path("temp")
        self._temp_dir.mkdir(exist_ok=True)

    def set_client(self, client: WeixinClient) -> None:
        """设置微信客户端"""
        self.client = client

    def _get_user_context(self, user_id: str) -> UserContext:
        """获取用户上下文"""
        if user_id not in self._user_contexts:
            self._user_contexts[user_id] = UserContext()
        return self._user_contexts[user_id]

    def _check_allow_to_chat(self, user_id: str) -> bool:
        """检查是否允许聊天"""
        chat_config = global_config.chat

        # 检查黑名单
        if user_id in chat_config.ban_user_id:
            logger.warning(f"用户 {user_id} 在黑名单中，消息被丢弃")
            return False

        # 检查私聊白名单/黑名单
        if chat_config.private_list_type == "whitelist":
            if user_id not in chat_config.private_list:
                logger.warning(f"用户 {user_id} 不在私聊白名单中，消息被丢弃")
                return False
        elif chat_config.private_list_type == "blacklist":
            if user_id in chat_config.private_list:
                logger.warning(f"用户 {user_id} 在私聊黑名单中，消息被丢弃")
                return False

        return True

    async def handle_inbound_message(self, msg: dict[str, Any]) -> Optional[MessageBase]:
        """处理接收到的微信消息，转换为 maim_message 格式"""
        from_user_id = str(msg.get("from_user_id", "")).strip()
        if not from_user_id:
            logger.debug("消息缺少 from_user_id，跳过")
            return None

        # 检查是否允许聊天
        if not self._check_allow_to_chat(from_user_id):
            return None

        # 保存 context_token
        context_token = str(msg.get("context_token", "")).strip()
        if context_token:
            user_ctx = self._get_user_context(from_user_id)
            user_ctx.context_token = context_token
            user_ctx.last_active = time.time()

        # 解析消息内容
        item_list = cast(list[dict[str, Any]], msg.get("item_list", []))
        if not item_list:
            logger.debug("消息 item_list 为空，跳过")
            return None

        # 转换消息段
        seg_list = await self._item_list_to_seg_list(item_list)
        if not seg_list:
            logger.warning("消息转换后为空，跳过")
            return None

        # 构建消息文本
        message_text = self._extract_text_from_item_list(item_list)

        # 构建用户信息
        user_info = UserInfo(
            platform=global_config.maibot_server.platform_name,
            user_id=from_user_id,
            user_nickname=from_user_id,  # 微信个人号没有昵称接口
            user_cardname=None,
        )

        # 微信个人号没有群聊概念，group_info 为 None
        group_info: Optional[GroupInfo] = None

        # 格式信息
        format_info = FormatInfo(
            content_format=["text", "image", "voice", "video", "file"],
            accept_format=["text", "image", "voice", "video", "file"],
        )

        # 消息信息
        message_id = str(msg.get("message_id") or msg.get("msg_id") or uuid.uuid4().hex)
        create_time = msg.get("create_time_ms") or msg.get("create_time")
        if isinstance(create_time, (int, float)) and create_time > 1_000_000_000_000:
            timestamp = int(float(create_time) / 1000)
        elif isinstance(create_time, (int, float)):
            timestamp = int(create_time)
        else:
            timestamp = int(time.time())

        message_info = BaseMessageInfo(
            platform=global_config.maibot_server.platform_name,
            message_id=message_id,
            time=timestamp,
            user_info=user_info,
            group_info=group_info,
            template_info=None,
            format_info=format_info,
            additional_config={"context_token": context_token} if context_token else {},
        )

        # 构建消息段
        submit_seg = Seg(type="seglist", data=seg_list) if len(seg_list) > 1 else seg_list[0]

        # 创建 MessageBase
        message_base = MessageBase(
            message_info=message_info,
            message_segment=submit_seg,
            raw_message=message_text,
        )

        logger.info(f"收到微信消息: user_id={from_user_id}, text={message_text[:50]}...")
        return message_base

    async def _item_list_to_seg_list(self, item_list: list[dict[str, Any]]) -> List[Seg]:
        """将微信 item_list 转换为 maim_message Seg 列表"""
        seg_list: List[Seg] = []

        for item in item_list:
            item_type = int(item.get("type") or 0)

            try:
                seg = await self._convert_item_to_seg(item, item_type)
                if seg:
                    seg_list.append(seg)
            except Exception as e:
                logger.error(f"转换消息项失败: type={item_type}, error={e}")

        return seg_list

    async def _convert_item_to_seg(self, item: dict[str, Any], item_type: int) -> Optional[Seg]:
        """转换单个消息项为 Seg"""
        if item_type == self.TEXT_ITEM_TYPE:
            # 文本消息
            text = str(item.get("text_item", {}).get("text", "")).strip()
            if text:
                return Seg(type="text", data=text)
            return None

        elif item_type == self.IMAGE_ITEM_TYPE:
            # 图片消息
            return await self._handle_image_item(item)

        elif item_type == self.VOICE_ITEM_TYPE:
            # 语音消息
            return await self._handle_voice_item(item)

        elif item_type == self.VIDEO_ITEM_TYPE:
            # 视频消息
            return await self._handle_video_item(item)

        elif item_type == self.FILE_ITEM_TYPE:
            # 文件消息
            return await self._handle_file_item(item)

        else:
            logger.warning(f"未知的消息类型: {item_type}")
            return None

    async def _handle_image_item(self, item: dict[str, Any]) -> Optional[Seg]:
        """处理图片消息项"""
        if not self.client:
            return None

        image_item = cast(dict[str, Any], item.get("image_item", {}) or {})
        media = cast(dict[str, Any], image_item.get("media", {}) or {})
        encrypted_query_param = str(media.get("encrypt_query_param", "")).strip()

        if not encrypted_query_param:
            return None

        try:
            # 获取 AES 密钥
            image_aes_key = str(image_item.get("aeskey", "")).strip()
            if image_aes_key:
                aes_key_value = base64.b64encode(bytes.fromhex(image_aes_key)).decode("utf-8")
            else:
                aes_key_value = str(media.get("aes_key", "")).strip()

            if aes_key_value:
                content = await self.client.download_and_decrypt_media(
                    encrypted_query_param, aes_key_value
                )
            else:
                content = await self.client.download_cdn_bytes(encrypted_query_param)

            # 转换为 base64
            image_base64 = base64.b64encode(content).decode("utf-8")
            return Seg(type="image", data=image_base64)

        except Exception as e:
            logger.error(f"下载图片失败: {e}")
            return Seg(type="text", data="[图片]")

    async def _handle_voice_item(self, item: dict[str, Any]) -> Optional[Seg]:
        """处理语音消息项"""
        if not self.client:
            return None

        voice_item = cast(dict[str, Any], item.get("voice_item", {}) or {})
        media = cast(dict[str, Any], voice_item.get("media", {}) or {})
        encrypted_query_param = str(media.get("encrypt_query_param", "")).strip()
        aes_key_value = str(media.get("aes_key", "")).strip()

        if not encrypted_query_param or not aes_key_value:
            return None

        # 尝试获取语音转文字
        voice_text = str(voice_item.get("text", "")).strip()
        if voice_text:
            return Seg(type="text", data=f"[语音] {voice_text}")

        try:
            content = await self.client.download_and_decrypt_media(
                encrypted_query_param, aes_key_value
            )
            voice_base64 = base64.b64encode(content).decode("utf-8")
            return Seg(type="voice", data=voice_base64)
        except Exception as e:
            logger.error(f"下载语音失败: {e}")
            return Seg(type="text", data="[语音]")

    async def _handle_video_item(self, item: dict[str, Any]) -> Optional[Seg]:
        """处理视频消息项"""
        if not self.client:
            return None

        video_item = cast(dict[str, Any], item.get("video_item", {}) or {})
        media = cast(dict[str, Any], video_item.get("media", {}) or {})
        encrypted_query_param = str(media.get("encrypt_query_param", "")).strip()
        aes_key_value = str(media.get("aes_key", "")).strip()

        if not encrypted_query_param or not aes_key_value:
            return None

        try:
            content = await self.client.download_and_decrypt_media(
                encrypted_query_param, aes_key_value
            )
            video_base64 = base64.b64encode(content).decode("utf-8")
            return Seg(type="video", data=video_base64)
        except Exception as e:
            logger.error(f"下载视频失败: {e}")
            return Seg(type="text", data="[视频]")

    async def _handle_file_item(self, item: dict[str, Any]) -> Optional[Seg]:
        """处理文件消息项"""
        file_item = cast(dict[str, Any], item.get("file_item", {}) or {})
        file_name = str(file_item.get("file_name", "未知文件")).strip()
        file_len = str(file_item.get("len", "未知大小"))

        # 返回文件信息作为文本
        return Seg(type="text", data=f"[文件: {file_name}, 大小: {file_len}字节]")

    def _extract_text_from_item_list(self, item_list: list[dict[str, Any]]) -> str:
        """从 item_list 提取文本内容"""
        text_parts: List[str] = []

        for item in item_list:
            item_type = int(item.get("type") or 0)

            if item_type == self.TEXT_ITEM_TYPE:
                text = str(item.get("text_item", {}).get("text", "")).strip()
                if text:
                    text_parts.append(text)
            elif item_type == self.IMAGE_ITEM_TYPE:
                text_parts.append("[图片]")
            elif item_type == self.VOICE_ITEM_TYPE:
                voice_text = str(item.get("voice_item", {}).get("text", "")).strip()
                if voice_text:
                    text_parts.append(f"[语音] {voice_text}")
                else:
                    text_parts.append("[语音]")
            elif item_type == self.FILE_ITEM_TYPE:
                file_name = str(item.get("file_item", {}).get("file_name", "文件")).strip()
                text_parts.append(f"[文件: {file_name}]")
            elif item_type == self.VIDEO_ITEM_TYPE:
                text_parts.append("[视频]")

        return "\n".join(text_parts).strip()

    def get_context_token(self, user_id: str) -> str:
        """获取用户的 context_token"""
        user_ctx = self._get_user_context(user_id)
        return user_ctx.context_token


# 全局消息处理器实例
message_handler = MessageHandler()
