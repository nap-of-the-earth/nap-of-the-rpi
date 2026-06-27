# ----------------------------------------------------------------------------------------------------
# logger.py
# ----------------------------------------------------------------------------------------------------

"""
Logging utility: configurable rotating file logger with console output.

Provides a centralized logging setup for all modules. Each module calls:
    from utils.logger import get_logger
    logger = get_logger(__name__)

This gives every module a logger that:
- Writes to a rotating file (prevents filling up the Pi's SD card)
- Also outputs to console (for development/debugging)
- Uses a consistent format across all modules
- Respects the configured log level (DEBUG, INFO, WARNING, ERROR)

Rotating log files:
- When the log file reaches max_bytes, it's renamed to .log.1
- Up to backup_count old files are kept (.log.1, .log.2, .log.3)
- Oldest files are deleted automatically
- Default: 5MB per file, 3 backups = max 20MB total log storage
"""

# ----------------------------------------------------------------------------------------------------
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ----------------------------------------------------------------------------------------------------
import logging
import sys


# ----------------------------------------------------------------------------------------------------
# Module-level flag to track if logging has been configured.
# We only want to configure the root logger once, even if get_logger() is
# called from multiple modules.
_configured = False

# Default values (used if Config hasn't been loaded yet or is unavailable)
_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_LOG_FILE = "/var/log/nap-of-the-rpi.log"
_DEFAULT_MAX_BYTES = 5242880  # 5MB
_DEFAULT_BACKUP_COUNT = 3
_DEFAULT_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"


# ----------------------------------------------------------------------------------------------------
def setup_logging(config=None) -> None:
    """
    Configure the root logger with file and console handlers.

    Should be called once at application startup (in main.py) after loading config.
    If called without config, uses sensible defaults.

    Args:
        config: Optional Config object. If provided, uses config.system.* values.
    """
    global _configured

    if _configured:
        return

    # Extract settings from config or use defaults
    if config is not None:
        log_level = getattr(config.system, "log_level", _DEFAULT_LOG_LEVEL)
        log_file = getattr(config.system, "log_file", _DEFAULT_LOG_FILE)
        max_bytes = getattr(config.system, "log_max_bytes", _DEFAULT_MAX_BYTES)
        backup_count = getattr(config.system, "log_backup_count", _DEFAULT_BACKUP_COUNT)
    else:
        log_level = _DEFAULT_LOG_LEVEL
        log_file = _DEFAULT_LOG_FILE
        max_bytes = _DEFAULT_MAX_BYTES
        backup_count = _DEFAULT_BACKUP_COUNT

    # Convert string level to logging constant (e.g., "INFO" → logging.INFO)
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Create formatter
    formatter = logging.Formatter(_DEFAULT_FORMAT)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Console handler (always added — useful for development and systemd journal)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (only if we can write to the log directory)
    try:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    except (PermissionError, OSError) as e:
        # If we can't write to the log file (e.g., /var/log without sudo),
        # just use console logging. Don't crash the app over logging.
        root_logger.warning(
            f"Cannot write to log file '{log_file}': {e}. "
            f"Using console-only logging."
        )

    _configured = True


# ----------------------------------------------------------------------------------------------------
def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger for a module.

    This is the main entry point for modules to get their logger.
    If setup_logging() hasn't been called yet, logs will still work
    (Python's default logging behavior), just without our formatting/file output.

    Args:
        name: Usually __name__ (gives the module's dotted path, e.g., "modules.pir_sensor")

    Returns:
        A logging.Logger instance configured with the application's handlers.

    Usage:
        from utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Something happened")
        logger.error("Something went wrong")
    """
    return logging.getLogger(name)


# ----------------------------------------------------------------------------------------------------
def reset_logging() -> None:
    """
    Reset logging configuration. Used in tests to ensure clean state.

    Removes all handlers from the root logger and resets the _configured flag.
    """
    global _configured
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    _configured = False
