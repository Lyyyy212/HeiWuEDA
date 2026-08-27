"""Error types returned by the guarded gateway."""


class GatewayError(RuntimeError):
    """Base class for gateway failures."""


class ContractError(GatewayError):
    """The API manifest or operation plan is invalid."""


class BridgeError(GatewayError):
    """The local official bridge returned an invalid response."""


class BridgeTimeoutError(BridgeError):
    """The bridge request timed out; the underlying EasyEDA call may still be running."""


class BridgeDiscoveryError(BridgeError):
    """No official bridge was found in the configured local port range."""


class AuthorizationError(GatewayError):
    """A guarded write lacks the required authorization evidence."""
