"""日志标准化配置"""

import logging
import os
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

# ======================
# 1. ContextVar 存 IP
# ======================
client_ip_ctx: ContextVar[str] = ContextVar("client_ip", default="-")
# ContextVar 按执行上下文隔离值，适合并发请求；请求入口需自行 set，并在 finally
# 中用对应 token 执行 reset。此配置模块本身不会从 HTTP 请求中自动提取 IP。


# ======================
# 2. 日志 Filter
# ======================
class ClientIPFilter(logging.Filter):
    """为每条日志补齐 client_ip 字段，保证带 IP 的格式器在无请求上下文时也可用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """写入当前上下文 IP 并返回 True，不根据 IP 丢弃任何日志。"""
        record.client_ip = client_ip_ctx.get()
        return True


def setup_logger(
        log_file: str = "./logs/app.log",
        level: int = logging.INFO,  # 日志级别：DEBUG / INFO / WARNING / ERROR
        log_format: str = '%(asctime)s [%(levelname)s] [IP:%(client_ip)s] %(name)s:%(lineno)d - %(message)s',
        date_format: str = '%Y-%m-%d %H:%M:%S',
        use_rotating: bool = False,  # 是否按大小轮转
        use_timed_rotating: bool = True,  # 是否按时间轮转
        max_bytes: int = 100 * 1024 * 1024,  # 轮转文件大小（100MB）
        backup_count: int = 7,  # 保留备份数
        when: str = 'D',  # 时间轮转单位（D=天，H=小时）
        interval: int = 1  # 时间轮转间隔
):
    """
    重新配置根日志器，自动创建目录，同时输出到文件和控制台，并支持日志轮转。

    每次调用都会清空根日志器现有处理器后重新添加，并非只初始化一次；应在应用
    启动阶段调用，避免与并发写日志或其他框架的日志配置互相干扰。若同时启用
    两种轮转，按大小轮转优先；两者都关闭则使用普通文件处理器。

    Args:
        log_file: 日志文件路径
        level: 日志级别
        log_format: 日志格式
        date_format: 时间格式
        use_rotating: 是否按文件大小轮转
        use_timed_rotating: 是否按时间轮转
        max_bytes: 轮转文件最大大小（仅use_rotating=True时生效）
        backup_count: 保留的备份日志数
        when: 时间轮转单位（仅use_timed_rotating=True时生效）
        interval: 时间轮转间隔（仅use_timed_rotating=True时生效）
    """
    # 1. 自动创建日志目录
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
        print(f"日志目录 {log_dir} 不存在，已自动创建")

    # 2. 获取根日志器，避免重复配置（清空已有处理器）
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # 清空已存在的处理器，防止重复输出
    if root_logger.handlers:
        root_logger.handlers.clear()

    # 3. 定义日志格式器
    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
    ip_filter = ClientIPFilter()
    # 4. 配置文件处理器（支持多种模式）
    file_handler = None
    if use_rotating:
        # 按文件大小轮转
        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
    elif use_timed_rotating:
        # 按时间轮转（推荐）
        file_handler = TimedRotatingFileHandler(
            filename=log_file,
            when=when,
            interval=interval,
            backupCount=backup_count,
            encoding='utf-8'
        )
        # 设置日志文件后缀（如 app.log.2025-08-21）
        file_handler.suffix = "%Y-%m-%d.log"
    else:
        # 普通文件输出（不轮转）
        file_handler = logging.FileHandler(
            filename=log_file,
            encoding='utf-8'
        )

    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    file_handler.addFilter(ip_filter)

    # 5. 配置控制台处理器（可选，注释掉则只输出到文件）
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    console_handler.addFilter(ip_filter)

    # 6. 添加处理器到根日志器
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)  # 如需仅文件输出，可注释此行


# 对外暴露简单的初始化接口（默认配置）
def init_default_logger():
    """初始化默认日志配置（按天轮转，保留7天，同时输出到控制台和文件）"""
    setup_logger(
        log_file=os.getenv("LOG_FILE", "./logs/app-data-storage.log"),
        level=logging.INFO,  # 避免 SDK 的 DEBUG 日志记录模型请求正文
        use_timed_rotating=True,
        backup_count=7
    )
