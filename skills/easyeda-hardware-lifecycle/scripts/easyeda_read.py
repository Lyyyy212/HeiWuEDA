#!/usr/bin/env python3
"""Discover the project-dedicated EasyEDA bridge and capture guarded read-only evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hwlifecycle.bridge import BridgeError, OfficialBridgeClient, discover_bridge
from hwlifecycle.evidence import record_active_schematic_capture
from hwlifecycle.io_utils import load_json
from hwlifecycle.read_adapter import capture_active_schematic
from hwlifecycle.session import capture_identity


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _add_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bridge-url", default="auto")
    parser.add_argument("--window-id")
    parser.add_argument("--timeout", type=float, default=30.0)


def _connect(args: argparse.Namespace) -> tuple[OfficialBridgeClient, str, dict]:
    discovery_timeout = min(max(args.timeout, 0.1), 2.0)
    endpoint = discover_bridge(args.bridge_url, timeout=discovery_timeout)
    client = OfficialBridgeClient(endpoint.base_url, timeout=args.timeout)
    window_id = client.resolve_window(args.window_id)
    return client, window_id, endpoint.health


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    discover = commands.add_parser("discover", help="discover bridge and list windows")
    discover.add_argument("--bridge-url", default="auto")
    discover.add_argument("--timeout", type=float, default=2.0)

    identity = commands.add_parser("identity", help="capture guarded active identity")
    _add_connection_arguments(identity)

    snapshot = commands.add_parser(
        "snapshot-active-schematic",
        help="capture components and pins from the active schematic page",
    )
    _add_connection_arguments(snapshot)
    snapshot.add_argument("--manifest", required=True, type=Path)
    snapshot.add_argument("--evidence-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "discover":
            endpoint = discover_bridge(
                args.bridge_url, timeout=min(max(args.timeout, 0.1), 2.0)
            )
            client = OfficialBridgeClient(endpoint.base_url, timeout=args.timeout)
            _print(
                {
                    "found": True,
                    "baseUrl": endpoint.base_url,
                    "health": endpoint.health,
                    "windows": client.windows(),
                }
            )
            return 0
        client, window_id, health = _connect(args)
        if args.command == "identity":
            identity = capture_identity(client, window_id=window_id)
            _print(
                {
                    "ok": True,
                    "health": health,
                    "identity": identity.to_dict(),
                }
            )
            return 0
        if args.command == "snapshot-active-schematic":
            manifest = load_json(args.manifest)
            capture = capture_active_schematic(
                client, window_id=window_id, manifest=manifest
            )
            evidence = record_active_schematic_capture(
                args.evidence_dir, capture, manifest
            )
            _print(
                {
                    "ok": True,
                    "readOnly": True,
                    "identity": capture["identity"],
                    "counts": capture["snapshot"]["counts"],
                    "planValidation": capture["validation"],
                    "evidence": evidence,
                }
            )
            return 0
        raise ValueError(f"unsupported command: {args.command}")
    except (BridgeError, OSError, ValueError) as error:
        _print({"ok": False, "error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
