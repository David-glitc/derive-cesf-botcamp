"""Non-trading network contract for the stock Hummingbot competition lane."""

MAINNET_CONNECTOR = "derive_perpetual"
MAINNET_HTTP_URL = "https://api.lyra.finance"
MAINNET_WS_URL = "wss://api.lyra.finance/ws"


def execution_environment():
    return {"network": "mainnet", "connector": MAINNET_CONNECTOR,
            "api_generation": "legacy_v2", "http_url": MAINNET_HTTP_URL,
            "ws_url": MAINNET_WS_URL}


def require_mainnet_connector(connector):
    if getattr(connector, "domain", None) != MAINNET_CONNECTOR:
        raise ValueError("mainnet_connector_domain_required")


def validate_installed_endpoints(constants):
    expected = {"DEFAULT_DOMAIN": MAINNET_CONNECTOR, "BASE_URL": MAINNET_HTTP_URL,
                "WSS_URL": MAINNET_WS_URL}
    for key, value in expected.items():
        if getattr(constants, key, None) != value:
            raise ValueError(f"unsupported_mainnet_connector:{key}")
