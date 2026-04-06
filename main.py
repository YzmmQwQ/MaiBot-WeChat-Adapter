"""
MaiBot 微信个人号适配器
基于微信 iLink Bot API，使用 maim_message 通信协议
"""
import asyncio
import sys
import time
import uuid
import qrcode as qrcode_lib
from io import StringIO
from typing import Optional
from urllib.parse import quote

# 添加当前目录到模块路径
sys.path.insert(0, '.')

from src.logger import logger
from src.config.config_manager import config_manager, global_config
from src.weixin_client import WeixinClient
from src.mmc_com_layer import mmc_start_com, mmc_stop_com
from src.recv_handler.message_handler import message_handler
from src.send_handler.main_send_handler import send_handler


class WeChatAdapter:
    """微信适配器主类"""

    def __init__(self):
        self.client: Optional[WeixinClient] = None
        self._shutdown_event = asyncio.Event()
        self._login_session: Optional[dict] = None
        self._sync_buf = ""
        self._qr_expired_count = 0

    async def run(self) -> None:
        """运行适配器"""
        try:
            # 初始化微信客户端
            self.client = WeixinClient(
                base_url=global_config.wechat.base_url,
                cdn_base_url=global_config.wechat.cdn_base_url,
                api_timeout_ms=global_config.wechat.api_timeout_ms,
                token=global_config.wechat.token or None,
            )

            # 设置消息处理器
            message_handler.set_client(self.client)
            send_handler.set_client(self.client)

            # 启动配置监控
            asyncio.create_task(config_manager.start_watch())

            # 同时运行微信消息轮询和 MaiBot 通信
            await asyncio.gather(
                self._wechat_poll_loop(),
                mmc_start_com(),
            )

        except asyncio.CancelledError:
            logger.debug("适配器被取消")
        except Exception as e:
            logger.exception(f"适配器运行异常: {e}")
        finally:
            await self._cleanup()

    async def _wechat_poll_loop(self) -> None:
        """微信消息轮询主循环"""
        while not self._shutdown_event.is_set():
            try:
                # 检查是否已登录
                if not self.client or not self.client.token:
                    # 执行登录流程
                    await self._login_flow()
                    continue

                # 轮询消息
                await self._poll_updates()

            except asyncio.TimeoutError:
                logger.debug("消息轮询超时")
            except Exception as e:
                logger.error(f"消息轮询异常: {e}")
                await asyncio.sleep(5)

    async def _login_flow(self) -> None:
        """登录流程"""
        # 检查是否有保存的 token
        if global_config.wechat.token:
            self.client.token = global_config.wechat.token
            logger.info("使用配置文件中的 token")
            return

        # 开始扫码登录
        if not self._is_login_session_valid():
            await self._start_login_session()

        # 轮询二维码状态
        if self._login_session:
            await self._poll_qr_status()

    async def _start_login_session(self) -> None:
        """开始登录会话，获取二维码"""
        try:
            data = await self.client.get_qrcode(global_config.wechat.bot_type)
            qrcode = str(data.get("qrcode", "")).strip()
            qrcode_url = str(data.get("qrcode_img_content", "")).strip()

            if not qrcode or not qrcode_url:
                raise RuntimeError("二维码响应缺少必要字段")

            # 生成可扫码的链接
            qr_console_url = (
                f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data="
                f"{quote(qrcode_url)}"
            )

            logger.info(f"请使用手机微信扫码登录，二维码链接: {qr_console_url}")

            # 尝试在终端打印二维码
            try:
                qr = qrcode_lib.QRCode(border=1)
                qr.add_data(qrcode_url)
                qr.make(fit=True)
                qr_buffer = StringIO()
                qr.print_ascii(out=qr_buffer, tty=False)
                logger.info(f"终端二维码:\n{qr_buffer.getvalue()}")
            except Exception as e:
                logger.warning(f"终端二维码打印失败: {e}")

            # 保存登录会话
            self._login_session = {
                "session_key": str(uuid.uuid4()),
                "qrcode": qrcode,
                "qrcode_img_content": qrcode_url,
                "started_at": time.time(),
                "status": "wait",
                "bot_token": None,
                "account_id": None,
                "base_url": None,
                "error": None,
            }
            self._qr_expired_count = 0

        except Exception as e:
            logger.error(f"获取登录二维码失败: {e}")
            await asyncio.sleep(5)

    def _is_login_session_valid(self) -> bool:
        """检查登录会话是否有效"""
        if not self._login_session:
            return False
        # 二维码有效期 5 分钟
        return (time.time() - self._login_session.get("started_at", 0)) * 1000 < 5 * 60_000

    async def _poll_qr_status(self) -> None:
        """轮询二维码状态"""
        if not self._login_session:
            return

        try:
            data = await self.client.poll_qr_status(
                self._login_session["qrcode"],
                global_config.wechat.long_poll_timeout_ms,
            )

            status = str(data.get("status", "wait")).strip()
            self._login_session["status"] = status

            if status == "expired":
                self._qr_expired_count += 1
                if self._qr_expired_count > 3:
                    logger.warning("二维码过期次数过多，等待下次重试")
                    self._login_session = None
                    return

                logger.info(f"二维码已过期，正在刷新 ({self._qr_expired_count}/3)")
                await self._start_login_session()
                return

            if status == "confirmed":
                bot_token = data.get("bot_token")
                account_id = data.get("ilink_bot_id")
                base_url = data.get("baseurl")

                if not bot_token:
                    self._login_session["error"] = "登录返回成功但未返回 token"
                    return

                # 保存登录信息
                self.client.token = str(bot_token)
                self._login_session["bot_token"] = str(bot_token)
                self._login_session["account_id"] = str(account_id) if account_id else None

                # 更新配置
                global_config.wechat.token = str(bot_token)
                if account_id:
                    global_config.wechat.account_id = str(account_id)
                if base_url:
                    self.client.base_url = str(base_url).rstrip("/")
                config_manager.save()

                logger.info(f"登录成功，account_id={account_id}")

            elif status == "canceled":
                logger.warning("用户取消扫码")
                self._login_session = None

        except asyncio.TimeoutError:
            pass  # 长轮询超时，正常
        except Exception as e:
            logger.error(f"轮询二维码状态失败: {e}")
            await asyncio.sleep(2)

    async def _poll_updates(self) -> None:
        """轮询微信消息"""
        data = await self.client.get_updates(
            self._sync_buf,
            global_config.wechat.long_poll_timeout_ms,
        )

        ret = int(data.get("ret") or 0)
        errcode = data.get("errcode", 0)

        if ret != 0 or (errcode and int(errcode) != 0):
            errmsg = str(data.get("errmsg", ""))
            logger.warning(f"获取消息失败: ret={ret}, errcode={errcode}, errmsg={errmsg}")
            return

        # 更新同步缓冲区
        if data.get("get_updates_buf"):
            self._sync_buf = str(data.get("get_updates_buf"))

        # 处理消息
        msgs = data.get("msgs", [])
        if isinstance(msgs, list):
            for msg in msgs:
                if self._shutdown_event.is_set():
                    return
                if not isinstance(msg, dict):
                    continue

                # 处理消息并转发给 MaiBot
                message_base = await message_handler.handle_inbound_message(msg)
                if message_base:
                    await self._forward_to_maibot(message_base)

    async def _forward_to_maibot(self, message_base) -> None:
        """转发消息到 MaiBot"""
        from src.mmc_com_layer import router

        if router:
            try:
                await router.send_message(message_base)
                logger.debug("消息已转发到 MaiBot")
            except Exception as e:
                logger.error(f"转发消息到 MaiBot 失败: {e}")

    async def _cleanup(self) -> None:
        """清理资源"""
        logger.info("正在清理资源...")

        self._shutdown_event.set()

        if self.client:
            await self.client.close()

        await mmc_stop_com()

        logger.info("资源清理完成")

    async def terminate(self) -> None:
        """终止适配器"""
        self._shutdown_event.set()


# 全局适配器实例
adapter: Optional[WeChatAdapter] = None


async def main():
    """主函数"""
    global adapter

    logger.info("正在启动 MaiBot-WeChat-Adapter...")
    logger.debug(f"日志等级: {global_config.debug.level}")

    adapter = WeChatAdapter()
    await adapter.run()


async def graceful_shutdown(silent: bool = False):
    """优雅关闭"""
    if not silent:
        logger.info("正在关闭适配器...")

    if adapter:
        await adapter.terminate()

    # 取消所有任务
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        if not task.done():
            task.cancel()

    if tasks:
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=3
            )
        except asyncio.TimeoutError:
            pass

    if not silent:
        logger.info("适配器已关闭")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.warning("收到中断信号，正在优雅关闭...")
        try:
            loop.run_until_complete(graceful_shutdown(silent=False))
        except Exception:
            pass
    except Exception as e:
        logger.error(f"主程序异常: {str(e)}")
        try:
            loop.run_until_complete(graceful_shutdown(silent=True))
        except Exception:
            pass
        sys.exit(1)
    finally:
        if loop and not loop.is_closed():
            loop.close()
        sys.exit(0)
