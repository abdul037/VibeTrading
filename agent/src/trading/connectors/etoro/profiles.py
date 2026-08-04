"""eToro connector profile definitions (demo only)."""

DEMO_PROFILE = {
    "name": "etoro-demo",
    "description": "eToro demo/paper account — all trades are simulated",
    "profile": "demo",
    "base_url": "https://public-api.etoro.com",
    "tap_credential": "etoro",
    "supported_order_types": ["mkt", "lmt"],
    "supported_settlement_types": ["cfd", "real"],
    "rate_limit_writes_per_minute": 20,
    "rate_limit_reads_per_minute": 60,
}

ALL_PROFILES = [DEMO_PROFILE]
