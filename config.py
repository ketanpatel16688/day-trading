import json
import logging
from pathlib import Path
from typing import Any, Dict


def load_config(path: Path = Path("config.json")) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    if "logging" not in config:
        raise ValueError("Missing required 'logging' section in config.json")

    return config


def _ensure_log_directory(path: str) -> None:
    log_path = Path(path).resolve().parent
    log_path.mkdir(parents=True, exist_ok=True)


def configure_logging(config: Dict[str, Any]) -> Dict[str, logging.Logger]:
    logging_config = config.get("logging", {})
    # Default to WARNING so INFO/DEBUG are disabled unless explicitly configured
    log_level = logging_config.get("log_level", "WARNING").upper()
    root_level = getattr(logging, log_level, logging.INFO)

    logging.basicConfig(
        level=root_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )

    # Silence overly-verbose logs from the IB API utility module
    # (set to WARNING to suppress INFO/DEBUG emitted by ibapi.util)
    try:
        logging.getLogger("ibapi.util").setLevel(logging.WARNING)
        logging.getLogger("ibapi").setLevel(logging.WARNING)
    except Exception:
        # best-effort: ignore failures configuring third-party loggers
        pass

    _ensure_log_directory(logging_config.get("error_log", "logs/error.log"))
    _ensure_log_directory(logging_config.get("trade_log", "logs/trade.log"))
    _ensure_log_directory(logging_config.get("execution_log", "logs/execution.log"))

    error_logger = logging.getLogger("error")
    trade_logger = logging.getLogger("trade")
    execution_logger = logging.getLogger("execution")

    error_handler = logging.FileHandler(logging_config.get("error_log", "logs/error.log"), encoding="utf-8")
    trade_handler = logging.FileHandler(logging_config.get("trade_log", "logs/trade.log"), encoding="utf-8")
    execution_handler = logging.FileHandler(logging_config.get("execution_log", "logs/execution.log"), encoding="utf-8")

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    error_handler.setFormatter(formatter)
    trade_handler.setFormatter(formatter)
    execution_handler.setFormatter(formatter)

    error_logger.setLevel(logging.ERROR)
    # Respect configured root level for standard loggers so INFO is off by default
    trade_logger.setLevel(root_level)
    execution_logger.setLevel(root_level)

    error_logger.addHandler(error_handler)
    trade_logger.addHandler(trade_handler)
    execution_logger.addHandler(execution_handler)

    return {
        "error": error_logger,
        "trade": trade_logger,
        "execution": execution_logger,
    }
