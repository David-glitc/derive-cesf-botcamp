"""Bounded native V3 option quotes inside the controller, without a sidecar."""
import asyncio

from src.data.records import normalize_option, normalize_perp


class OptionsFeed:
    def __init__(self, transport, currency):
        if currency not in ("ETH", "BTC"):
            raise ValueError("unsupported_option_currency")
        self.transport, self.currency = transport, currency
        self.definitions = []
        self.definitions_at = -float("inf")
        self.sample_at = -float("inf")
        self.market = None
        self.error = None
        self._task = None

    def poll(self):
        # Public chain reads must not delay the controller's perp risk/exit
        # ticks. The planner independently rejects stale completed snapshots.
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.refresh())

    def close(self):
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def refresh(self):
        now = self.transport.clock()
        if 0 <= now - self.sample_at < 2:
            return self.market
        self.sample_at = now
        try:
            if not 0 <= now - self.definitions_at < 300:
                rows = []
                for page in range(1, 7):
                    result = await self.transport.call("public/get_all_instruments", {
                        "currency": self.currency, "instrument_type": "option", "expired": False,
                        "page": page, "page_size": 500}, private=False)
                    rows.extend(result["instruments"])
                    if page >= result["pagination"]["num_pages"]:
                        break
                else:
                    raise ValueError("option_instrument_pagination_limit")
                if len({r["instrument_name"] for r in rows}) != len(rows):
                    raise ValueError("duplicate_option_instrument")
                self.definitions, self.definitions_at = rows, self.transport.clock()
            selected = [d for d in self.definitions if d["is_active"] and
                        2 * 86400 <= d["option_details"]["expiry"] - now <= 5 * 86400]
            expiries = sorted({int(d["instrument_name"].split("-")[1]) for d in selected})
            if len(expiries) > 4:
                raise ValueError("option_expiry_capture_limit")
            chains = await asyncio.gather(
                *(self.transport.call("public/get_tickers", {"currency": self.currency,
                    "instrument_type": "option", "expiry_date": expiry}, private=False) for expiry in expiries))
            # Fetch index last so slow chain requests cannot silently age it.
            perp = await self.transport.call("public/get_ticker", {
                "instrument_name": self.currency + "-PERP"}, private=False)
            now = self.transport.clock()
            tickers = {}
            for chain in chains:
                batch = chain["tickers"]
                if not isinstance(batch, dict) or tickers.keys() & batch.keys():
                    raise ValueError("option_ticker_capture_invalid")
                tickers.update(batch)
                if len(tickers) > 3000:
                    raise ValueError("option_ticker_capture_limit")
            options = []
            for definition in selected:
                name = definition["instrument_name"]
                if name not in tickers or not 2 * 86400 <= definition["option_details"]["expiry"] - now <= 5 * 86400:
                    continue
                options.append(normalize_option(definition, tickers[name], self.currency, now))
            self.market = {"perp": normalize_perp(perp, self.currency, now), "options": options,
                           "received_at": now, "api_generation": "v3"}
            self.error = None
        except Exception as exc:
            self.market = None  # no stale quote fallback, but continue protective exits
            self.error = "native_option_feed_unavailable:" + type(exc).__name__
        return self.market
