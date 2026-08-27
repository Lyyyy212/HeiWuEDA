"""Compatibility entrypoint for the guarded EasyEDA runtime gateway."""

from _gateway_bootstrap import activate_gateway

activate_gateway()

from easyeda_gateway.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
