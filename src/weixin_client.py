"""
微信 iLink Bot API 客户端
基于 AstrBot weixin_oc 实现，适配 maim_message 消息格式
"""
from __future__ import annotations

import base64
import hashlib
import json
import random
import uuid
from pathlib import Path
from typing import Any, Optional, cast
from urllib.parse import quote

import aiohttp
from Crypto.Cipher import AES

from src.logger import logger


class WeixinClient:
    """微信 iLink Bot API 客户端"""

    def __init__(
        self,
        *,
        base_url: str = "https://ilinkai.weixin.qq.com",
        cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c",
        api_timeout_ms: int = 15000,
        token: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cdn_base_url = cdn_base_url.rstrip("/")
        self.api_timeout_ms = api_timeout_ms
        self.token = token
        self._http_session: Optional[aiohttp.ClientSession] = None

        # 同步缓冲区，用于消息同步
        self._sync_buf = ""

    async def ensure_http_session(self) -> None:
        """确保 HTTP 会话存在"""
        if self._http_session is None or self._http_session.closed:
            timeout = aiohttp.ClientTimeout(total=self.api_timeout_ms / 1000)
            self._http_session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        """关闭 HTTP 会话"""
        if self._http_session is not None and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    def _build_base_headers(self, token_required: bool = False) -> dict[str, str]:
        """构建基础请求头"""
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": base64.b64encode(
                str(random.getrandbits(32)).encode("utf-8")
            ).decode("utf-8"),
        }
        if token_required and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _resolve_url(self, endpoint: str) -> str:
        """解析完整 URL"""
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _build_cdn_upload_url(self, upload_param: str, file_key: str) -> str:
        """构建 CDN 上传 URL"""
        return (
            f"{self.cdn_base_url}/upload?"
            f"encrypted_query_param={quote(upload_param)}&filekey={quote(file_key)}"
        )

    def _build_cdn_download_url(self, encrypted_query_param: str) -> str:
        """构建 CDN 下载 URL"""
        return (
            f"{self.cdn_base_url}/download?"
            f"encrypted_query_param={quote(encrypted_query_param)}"
        )

    # ==================== AES 加解密工具 ====================

    @staticmethod
    def aes_padded_size(size: int) -> int:
        """计算 AES 填充后的尺寸"""
        return size + (16 - (size % 16) or 16)

    @staticmethod
    def pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
        """PKCS7 填充"""
        pad_len = block_size - (len(data) % block_size)
        if pad_len == 0:
            pad_len = block_size
        return data + bytes([pad_len]) * pad_len

    @staticmethod
    def pkcs7_unpad(data: bytes, block_size: int = 16) -> bytes:
        """PKCS7 去填充"""
        if not data:
            return data
        pad_len = data[-1]
        if pad_len <= 0 or pad_len > block_size:
            return data
        if data[-pad_len:] != bytes([pad_len]) * pad_len:
            return data
        return data[:-pad_len]

    @staticmethod
    def parse_media_aes_key(aes_key_value: str) -> bytes:
        """解析媒体 AES 密钥"""
        normalized = aes_key_value.strip()
        if not normalized:
            raise ValueError("empty media aes key")
        padded = normalized + "=" * (-len(normalized) % 4)
        decoded = base64.b64decode(padded)
        if len(decoded) == 16:
            return decoded
        decoded_text = decoded.decode("ascii", errors="ignore")
        if len(decoded) == 32 and all(
            c in "0123456789abcdefABCDEF" for c in decoded_text
        ):
            return bytes.fromhex(decoded_text)
        raise ValueError("unsupported media aes key format")

    # ==================== CDN 操作 ====================

    async def upload_to_cdn(
        self,
        upload_full_url: str,
        upload_param: str,
        file_key: str,
        aes_key_hex: str,
        media_path: Path,
    ) -> str:
        """上传媒体文件到 CDN"""
        if upload_full_url:
            cdn_url = upload_full_url
        elif upload_param:
            cdn_url = self._build_cdn_upload_url(upload_param, file_key)
        else:
            raise ValueError("CDN upload URL missing")

        raw_data = media_path.read_bytes()
        logger.debug(
            f"准备上传到 CDN: file={media_path.name}, size={len(raw_data)}, md5={hashlib.md5(raw_data).hexdigest()}"
        )

        cipher = AES.new(bytes.fromhex(aes_key_hex), AES.MODE_ECB)
        encrypted = cipher.encrypt(self.pkcs7_pad(raw_data))

        await self.ensure_http_session()
        assert self._http_session is not None
        timeout = aiohttp.ClientTimeout(total=self.api_timeout_ms / 1000)

        async with self._http_session.post(
            cdn_url,
            data=encrypted,
            headers={"Content-Type": "application/octet-stream"},
            timeout=timeout,
        ) as resp:
            detail = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"upload media to cdn failed: {resp.status} {detail}")

            download_param = resp.headers.get("x-encrypted-param")
            if not download_param:
                raise RuntimeError("upload media to cdn failed: missing x-encrypted-param")
            return download_param

    async def download_cdn_bytes(self, encrypted_query_param: str) -> bytes:
        """从 CDN 下载加密数据"""
        await self.ensure_http_session()
        assert self._http_session is not None
        timeout = aiohttp.ClientTimeout(total=self.api_timeout_ms / 1000)

        async with self._http_session.get(
            self._build_cdn_download_url(encrypted_query_param),
            timeout=timeout,
        ) as resp:
            if resp.status >= 400:
                detail = await resp.text()
                raise RuntimeError(f"download media from cdn failed: {resp.status} {detail}")
            return await resp.read()

    async def download_and_decrypt_media(
        self,
        encrypted_query_param: str,
        aes_key_value: str,
    ) -> bytes:
        """下载并解密媒体文件"""
        encrypted = await self.download_cdn_bytes(encrypted_query_param)
        key = self.parse_media_aes_key(aes_key_value)
        cipher = AES.new(key, AES.MODE_ECB)
        return self.pkcs7_unpad(cipher.decrypt(encrypted))

    # ==================== API 请求 ====================

    async def request_json(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[dict[str, Any]] = None,
        payload: Optional[dict[str, Any]] = None,
        token_required: bool = False,
        timeout_ms: Optional[int] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """发送 JSON 请求"""
        await self.ensure_http_session()
        assert self._http_session is not None

        req_timeout = timeout_ms if timeout_ms is not None else self.api_timeout_ms
        timeout = aiohttp.ClientTimeout(total=req_timeout / 1000)
        merged_headers = self._build_base_headers(token_required=token_required)
        if headers:
            merged_headers.update(headers)

        async with self._http_session.request(
            method,
            self._resolve_url(endpoint),
            params=params,
            json=payload,
            headers=merged_headers,
            timeout=timeout,
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"{method} {endpoint} failed: {resp.status} {text}")
            if not text:
                return {}
            return cast(dict[str, Any], json.loads(text))

    # ==================== 登录相关 ====================

    async def get_qrcode(self, bot_type: str = "3") -> dict[str, Any]:
        """获取登录二维码"""
        return await self.request_json(
            "GET",
            "ilink/bot/get_bot_qrcode",
            params={"bot_type": bot_type},
            token_required=False,
            timeout_ms=15000,
        )

    async def poll_qr_status(self, qrcode: str, timeout_ms: int = 35000) -> dict[str, Any]:
        """轮询二维码状态"""
        return await self.request_json(
            "GET",
            "ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode},
            token_required=False,
            timeout_ms=timeout_ms,
            headers={"iLink-App-ClientVersion": "1"},
        )

    # ==================== 消息相关 ====================

    async def get_updates(self, sync_buf: str = "", timeout_ms: int = 35000) -> dict[str, Any]:
        """获取新消息"""
        return await self.request_json(
            "POST",
            "ilink/bot/getupdates",
            payload={
                "base_info": {
                    "channel_version": "maibot-wechat-adapter",
                },
                "get_updates_buf": sync_buf,
            },
            token_required=True,
            timeout_ms=timeout_ms,
        )

    async def send_message(
        self,
        user_id: str,
        item_list: list[dict[str, Any]],
        context_token: str,
    ) -> dict[str, Any]:
        """发送消息"""
        return await self.request_json(
            "POST",
            "ilink/bot/sendmessage",
            payload={
                "base_info": {
                    "channel_version": "maibot-wechat-adapter",
                },
                "msg": {
                    "from_user_id": "",
                    "to_user_id": user_id,
                    "client_id": uuid.uuid4().hex,
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": item_list,
                },
            },
            token_required=True,
        )

    async def get_upload_url(
        self,
        user_id: str,
        file_key: str,
        media_type: int,
        raw_size: int,
        raw_md5: str,
        aes_key_hex: str,
    ) -> dict[str, Any]:
        """获取媒体上传 URL"""
        ciphertext_size = self.aes_padded_size(raw_size)
        return await self.request_json(
            "POST",
            "ilink/bot/getuploadurl",
            payload={
                "filekey": file_key,
                "media_type": media_type,
                "to_user_id": user_id,
                "rawsize": raw_size,
                "rawfilemd5": raw_md5,
                "filesize": ciphertext_size,
                "no_need_thumb": True,
                "aeskey": aes_key_hex,
                "base_info": {
                    "channel_version": "maibot-wechat-adapter",
                },
            },
            token_required=True,
        )

    # ==================== 输入状态 ====================

    async def get_typing_config(self, user_id: str, context_token: str) -> dict[str, Any]:
        """获取输入状态配置"""
        return await self.request_json(
            "POST",
            "ilink/bot/getconfig",
            payload={
                "ilink_user_id": user_id,
                "context_token": context_token,
                "base_info": {
                    "channel_version": "maibot-wechat-adapter",
                },
            },
            token_required=True,
        )

    async def send_typing_state(
        self,
        user_id: str,
        typing_ticket: str,
        cancel: bool = False,
    ) -> dict[str, Any]:
        """发送输入状态"""
        return await self.request_json(
            "POST",
            "ilink/bot/sendtyping",
            payload={
                "ilink_user_id": user_id,
                "typing_ticket": typing_ticket,
                "status": 2 if cancel else 1,
                "base_info": {
                    "channel_version": "maibot-wechat-adapter",
                },
            },
            token_required=True,
        )
