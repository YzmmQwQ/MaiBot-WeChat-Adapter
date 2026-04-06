import sys
import loguru
from pathlib import Path

# 创建日志目录
log_path = Path("logs")
log_path.mkdir(exist_ok=True)


def format_log(record):
    """格式化日志输出"""
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>\n"
    )


# 移除默认处理器
logger = loguru.logger
logger.remove()

# 添加控制台处理器
logger.add(
    sys.stdout,
    format=format_log,
    level="DEBUG",
    colorize=True,
    filter=lambda record: format_log(record) and record["extra"].get("module_name") != "maim_message",
)

# maim_message 单独处理
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>\n",
    level="DEBUG",
    colorize=True,
    filter=lambda record: record["extra"].get("module_name") == "maim_message",
)

# 添加文件处理器 - 主日志
logger.add(
    log_path / "adapter_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="7 days",
    level="DEBUG",
    encoding="utf-8",
    format=format_log,
)

# 添加文件处理器 - 错误日志
logger.add(
    log_path / "error_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    level="ERROR",
    encoding="utf-8",
    format=format_log,
)

# maim_message 的 logger
custom_logger = logger.bind(module_name="maim_message")
