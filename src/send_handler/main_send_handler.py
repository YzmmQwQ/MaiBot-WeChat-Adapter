"""
微信消息发送处理
将 maim_message 格式转换为微信消息并发送
"""
import base64
import hashlib
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from maim_message import MessageBase, Seg

from src.logger import logger
from src.config.config_manager import global_config
from src.weixin_client import WeixinClient
from src.recv_handler.message_handler import message_handler


class SendHandler:
    """微信消息发送处理器"""

    # 消息类型常量
    IMAGE_ITEM_TYPE = 2
    VOICE_ITEM_TYPE = 3
    FILE_ITEM_TYPE = 4
    VIDEO_ITEM_TYPE = 5

    # 媒体上传类型
    IMAGE_UPLOAD_TYPE = 1
    VIDEO_UPLOAD_TYPE = 2
    FILE_UPLOAD_TYPE = 3

    def __init__(self):
        self.client: Optional[WeixinClient] = None
        self._temp_dir = Path("temp")
        self._temp_dir.mkdir(exist_ok=True)

    def set_client(self, client: WeixinClient) -> None:
        """设置微信客户端"""
        self.client = client

    async def handle_message(self, raw_message_base_dict: dict) -> None:
        """处理来自 MaiBot 的消息"""
        try:
            raw_message_base = MessageBase.from_dict(raw_message_base_dict)
            message_segment: Seg = raw_message_base.message_segment
            logger.info("接收到来自 MaiBot 的消息，处理中")

            # 获取目标用户 ID
            user_info = raw_message_base.message_info.user_info
            target_user_id = user_info.user_id

            if not target_user_id:
                logger.error("消息缺少目标用户 ID")
                return

            # 获取 context_token
            context_token = message_handler.get_context_token(target_user_id)
            if not context_token:
                logger.warning(f"用户 {target_user_id} 没有 context_token，无法发送消息")
                return

            # 根据消息类型处理
            if message_segment.type == "command":
                await self._handle_command(raw_message_base, target_user_id, context_token)
            else:
                await self._handle_normal_message(raw_message_base, target_user_id, context_token)

        except Exception as e:
            logger.error(f"处理消息失败: {e}", exc_info=True)

    async def _handle_command(
        self,
        message_base: MessageBase,
        user_id: str,
        context_token: str,
    ) -> None:
        """处理命令消息"""
        logger.debug("微信适配器暂不支持命令消息")
        # TODO: 实现命令处理

    async def _handle_normal_message(
        self,
        message_base: MessageBase,
        user_id: str,
        context_token: str,
    ) -> None:
        """处理普通消息"""
        message_segment: Seg = message_base.message_segment
        item_list: List[dict[str, Any]] = []

        # 处理消息段
        if message_segment.type == "seglist":
            # 消息段列表
            for seg in message_segment.data:
                item = await self._convert_seg_to_item(seg, user_id)
                if item:
                    item_list.append(item)
        else:
            # 单个消息段
            item = await self._convert_seg_to_item(message_segment, user_id)
            if item:
                item_list.append(item)

        if not item_list:
            logger.warning("转换后消息为空，跳过发送")
            return

        # 发送消息
        try:
            if not self.client:
                logger.error("微信客户端未初始化")
                return

            await self.client.send_message(user_id, item_list, context_token)
            logger.info(f"消息发送成功: user_id={user_id}")

        except Exception as e:
            logger.error(f"发送消息失败: {e}")

    async def _convert_seg_to_item(self, seg: Seg, user_id: str) -> Optional[dict[str, Any]]:
        """将 maim_message Seg 转换为微信 item 格式"""
        if seg.type == "text":
            # 文本消息
            text = str(seg.data).strip()
            if text:
                return self._build_text_item(text)
            return None

        elif seg.type == "image":
            # 图片消息
            return await self._build_image_item(seg.data, user_id)

        elif seg.type == "voice":
            # 语音消息
            return await self._build_voice_item(seg.data, user_id)

        elif seg.type == "video":
            # 视频消息
            return await self._build_video_item(seg.data, user_id)

        else:
            logger.warning(f"不支持的消息段类型: {seg.type}")
            return None

    def _build_text_item(self, text: str) -> dict[str, Any]:
        """构建文本消息项"""
        return {
            "type": 1,
            "text_item": {
                "text": text,
            },
        }

    async def _build_image_item(self, image_data: Any, user_id: str) -> Optional[dict[str, Any]]:
        """构建图片消息项"""
        if not self.client:
            return None

        try:
            # 获取图片数据
            if isinstance(image_data, str):
                # base64 编码的图片
                raw_bytes = base64.b64decode(image_data)
            elif isinstance(image_data, bytes):
                raw_bytes = image_data
            else:
                logger.warning("不支持的图片数据格式")
                return None

            # 保存到临时文件
            temp_path = self._temp_dir / f"img_{uuid.uuid4().hex}.jpg"
            temp_path.write_bytes(raw_bytes)

            # 上传图片
            media_item = await self._prepare_media_item(
                user_id,
                temp_path,
                self.IMAGE_UPLOAD_TYPE,
                self.IMAGE_ITEM_TYPE,
            )

            # 清理临时文件
            temp_path.unlink(missing_ok=True)

            return media_item

        except Exception as e:
            logger.error(f"构建图片消息失败: {e}")
            return None

    async def _build_voice_item(self, voice_data: Any, user_id: str) -> Optional[dict[str, Any]]:
        """构建语音消息项"""
        # 微信个人号语音消息格式特殊，暂不支持
        logger.warning("微信个人号暂不支持发送语音消息")
        return None

    async def _build_video_item(self, video_data: Any, user_id: str) -> Optional[dict[str, Any]]:
        """构建视频消息项"""
        if not self.client:
            return None

        try:
            # 获取视频数据
            if isinstance(video_data, str):
                raw_bytes = base64.b64decode(video_data)
            elif isinstance(video_data, bytes):
                raw_bytes = video_data
            else:
                logger.warning("不支持的视频数据格式")
                return None

            # 保存到临时文件
            temp_path = self._temp_dir / f"video_{uuid.uuid4().hex}.mp4"
            temp_path.write_bytes(raw_bytes)

            # 上传视频
            media_item = await self._prepare_media_item(
                user_id,
                temp_path,
                self.VIDEO_UPLOAD_TYPE,
                self.VIDEO_ITEM_TYPE,
            )

            # 清理临时文件
            temp_path.unlink(missing_ok=True)

            return media_item

        except Exception as e:
            logger.error(f"构建视频消息失败: {e}")
            return None

    async def _prepare_media_item(
        self,
        user_id: str,
        media_path: Path,
        upload_media_type: int,
        item_type: int,
    ) -> Optional[dict[str, Any]]:
        """准备媒体消息项"""
        if not self.client:
            return None

        try:
            raw_bytes = media_path.read_bytes()
            raw_size = len(raw_bytes)
            raw_md5 = hashlib.md5(raw_bytes).hexdigest()
            file_key = uuid.uuid4().hex
            aes_key_hex = uuid.uuid4().bytes.hex()
            ciphertext_size = self.client.aes_padded_size(raw_size)

            # 获取上传 URL
            payload = await self.client.get_upload_url(
                user_id=user_id,
                file_key=file_key,
                media_type=upload_media_type,
                raw_size=raw_size,
                raw_md5=raw_md5,
                aes_key_hex=aes_key_hex,
            )

            upload_param = str(payload.get("upload_param", "")).strip()
            upload_full_url = str(payload.get("upload_full_url", "")).strip()

            if not upload_param and not upload_full_url:
                raise RuntimeError("获取上传 URL 失败")

            # 上传到 CDN
            encrypted_query_param = await self.client.upload_to_cdn(
                upload_full_url,
                upload_param,
                file_key,
                aes_key_hex,
                media_path,
            )

            aes_key_b64 = base64.b64encode(aes_key_hex.encode("utf-8")).decode("utf-8")
            media_payload = {
                "encrypt_query_param": encrypted_query_param,
                "aes_key": aes_key_b64,
                "encrypt_type": 1,
            }

            if item_type == self.IMAGE_ITEM_TYPE:
                return {
                    "type": self.IMAGE_ITEM_TYPE,
                    "image_item": {
                        "media": media_payload,
                        "mid_size": ciphertext_size,
                    },
                }
            elif item_type == self.VIDEO_ITEM_TYPE:
                return {
                    "type": self.VIDEO_ITEM_TYPE,
                    "video_item": {
                        "media": media_payload,
                        "video_size": ciphertext_size,
                    },
                }

            return None

        except Exception as e:
            logger.error(f"准备媒体消息失败: {e}")
            return None


# 全局发送处理器实例
send_handler = SendHandler()
