from loguru import logger

from parsetrail.core.settings import AppSettings

# Ensure log directory exists
defaults = AppSettings()
defaults.log_file.parent.mkdir(parents=True, exist_ok=True)

# Clear previous log handlers to avoid duplication
logger.remove()

# Configure stdout handler (default format)
logger.add(
    sink=lambda msg: print(msg, end=""),  # Keep stdout logging unchanged
    level="DEBUG",
    colorize=True,
)

# Configure file handler with desired format
logger.add(
    defaults.log_file,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    rotation="10 MB",  # Rotate logs when they reach 10MB
    retention="90 days",  # Keep logs for 90 days
    compression="zip",  # Compress old logs
)
