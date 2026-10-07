"""Bounded public-only V3 quote check. No credentials, orders or activation."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agents.mainnet import MAINNET_HTTP_URL
from src.data.options_feed import OptionsFeed


class PublicTransport:
    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers["User-Agent"] = "flyby-v3-public-check"

    def clock(self):
        return time.time()

    async def call(self, method, params, private=True):
        if private or method not in {"public/get_all_instruments", "public/get_ticker", "public/get_tickers"}:
            raise ValueError("public_only_check")
        response = await asyncio.to_thread(self.session.post, MAINNET_HTTP_URL + "/" + method,
                                          json=params, timeout=8, allow_redirects=False)
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            raise ValueError("public_rpc_rejected")
        return body["result"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--currency", choices=("ETH", "BTC"), default="ETH")
    args = parser.parse_args()
    feed = OptionsFeed(PublicTransport(), args.currency)
    market = asyncio.run(feed.refresh())
    result = {"api_generation": "v3", "currency": args.currency, "public_only": True,
              "feed_error": feed.error, "native_definitions": len(feed.definitions),
              "eligible_options": len(market["options"]) if market else 0,
              "quoted_options": sum(q["quoted"] for q in market["options"]) if market else 0,
              "fresh_perp_index": bool(market and market["perp"]["fresh"]),
              "orders_submitted": 0, "live_verified": False}
    print(json.dumps(result, indent=2))
    return 0 if market is not None and market["perp"]["fresh"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
