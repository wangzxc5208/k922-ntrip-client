"""Command-line entry point retained for headless deployments."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import ClientConfig, ConfigError
from .service import NtripService, ServiceEvent


LOG = logging.getLogger("k922_ntrip")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Receive CORS corrections and forward them to a K922 board over RS232."
    )
    parser.add_argument("--config", default="config.json", help="JSON config path (default: config.json)")
    parser.add_argument("--verbose", action="store_true", help="Show debug messages")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        config = ClientConfig.from_file(Path(args.config))
    except (ConfigError, OSError) as exc:
        LOG.error("%s", exc)
        return 2

    def log_event(event: ServiceEvent) -> None:
        if event.kind == "log":
            level = getattr(logging, event.data.get("level", "INFO"), logging.INFO)
            LOG.log(level, "%s", event.data.get("message", ""))
        elif args.verbose and event.kind == "stats":
            LOG.debug(
                "RS232 累计写入 %s B，差分速率 %.1f B/s，已重连 %s 次",
                event.data["bytes_received"],
                event.data["rate_bytes_per_second"],
                event.data["reconnects"],
            )
        elif args.verbose and event.kind == "gga_upload":
            LOG.debug("已向 CORS 上传有效 GGA")

    service = NtripService(config, log_event)
    try:
        return service.run()
    except KeyboardInterrupt:
        service.request_stop()
        LOG.info("Stopped by user")
        return 0
