import logging


class Logger:
    """Logger class for logging messages."""

    def __init__(self, name: str) -> None:
        """Initialize the logger with a given name."""
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG)
        self._handler = logging.StreamHandler()
        self._formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self._handler.setFormatter(self._formatter)
        self._logger.addHandler(self._handler)

    def _log(self, level: int, message: str) -> None:
        """Log a message with a given level."""
        self._logger.log(level, message)

    def debug(self, message: str) -> None:
        """Log a debug message."""
        self._log(logging.DEBUG, message)

    def info(self, message: str) -> None:
        """Log an info message."""
        self._log(logging.INFO, message)

    def warning(self, message: str) -> None:
        """Log a warning message."""
        self._log(logging.WARNING, message)

    def error(self, message: str) -> None:
        """Log an error message."""
        self._log(logging.ERROR, message)

    def critical(self, message: str) -> None:
        """Log a critical message."""
        self._log(logging.CRITICAL, message)
