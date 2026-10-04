"""Private stdio tools; operator-selected paths, no HTTP listener or order API."""
import argparse
import time

from src.runtime.bridge import RuntimeBridge


def build_server(bridge, clock=time.time):
    # Optional dependency belongs to Condor, not the Hummingbot controller.
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("flyby-runtime")

    @server.tool()
    def flyby_get_runtime_state() -> dict:
        """Read private portfolio/positions/market state. Stale/unknown is not flat."""
        return bridge.read_state(clock())

    @server.tool()
    def flyby_read_events(after_sequence: int = 0, limit: int = 64) -> dict:
        """Read bounded controller event tail; gaps require refreshing state."""
        return bridge.events(after_sequence, limit)

    @server.tool()
    def flyby_get_adjustment_status(request_id: str) -> dict:
        """Read a request receipt. Validated never means a verified exchange fill."""
        return bridge.status(request_id, clock())

    if bridge.writable:
        @server.tool()
        def flyby_submit_adjustment(request_id: str, session: str, basis_sequence: int,
                                    patch: dict, expires_in_seconds: int = 60) -> dict:
            """Queue a bounded lease for controller validation; never directly place orders.

            Read state immediately first. No budgets/leverage/signals/namespace
            writes. Veto, size 0..1, tighter confidence/cost gates, stop .5..1,
            TP 1..2, hold .5..1.5 (new perps only), owned close requests.
            """
            if type(expires_in_seconds) is not int or not 1 <= expires_in_seconds <= 60:
                raise ValueError("runtime_invalid_lease_duration")
            now = clock()
            return bridge.submit({"id": request_id, **bridge.owner, "session": session,
                                  "basis_sequence": basis_sequence, "issued_at": now,
                                  "expires_at": now + expires_in_seconds, "patch": patch}, now)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--controller-id", required=True)
    parser.add_argument("--account-binding", required=True)
    parser.add_argument("--enable-controls", action="store_true")
    args = parser.parse_args()
    bridge = RuntimeBridge(args.root, args.controller_id, args.account_binding, writable=args.enable_controls)
    build_server(bridge).run(transport="stdio")


if __name__ == "__main__":
    main()
