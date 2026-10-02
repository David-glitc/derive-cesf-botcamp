"""Tenor-specific observed IV/OI diagnostics; never claim signed dealer GEX."""
from src.data.records import number


def surface(options, now, spot, previous=None):
    spot = number(spot)
    if spot <= 0:
        raise ValueError("invalid surface spot")
    groups, rejected = {}, 0
    for q in options:
        try:
            if not q["active"] or not 0 <= now - number(q["timestamp"]) <= 5 or q["expiry"] <= now:
                rejected += 1
                continue
            iv, delta = number(q["pricing"]["iv"]), number(q["delta"])
            if (not .001 <= iv <= 5 or not -1 <= delta <= 1
                    or q["kind"] not in ("call", "put") or (delta > 0) != (q["kind"] == "call")):
                raise ValueError("invalid IV/delta")
            groups.setdefault(q["expiry"], []).append(q)
        except (ValueError, KeyError, TypeError):
            rejected += 1
    tenors = []
    for expiry, chain in sorted(groups.items()):
        def nearest(kind, delta):
            candidates = [q for q in chain if q["kind"] == kind and q["quoted"]
                          and abs(abs(q["delta"]) - delta) <= .08]
            return min(candidates, key=lambda q: abs(abs(q["delta"]) - delta)) if candidates else None
        call, put = nearest("call", .5), nearest("put", .5)
        c25, p25 = nearest("call", .25), nearest("put", .25)
        atm = (call["pricing"]["iv"] + put["pricing"]["iv"]) / 2 if call and put else None
        skew = p25["pricing"]["iv"] - c25["pricing"]["iv"] if p25 and c25 else None
        oi = [q for q in chain if q.get("oi") is not None]
        gamma = [q for q in oi if q["pricing"].get("gamma") is not None]
        proxy = sum(abs(number(q["pricing"]["gamma"])) * number(q["oi"]) for q in gamma)
        tenors.append({"expiry": expiry, "dte": (expiry - now) / 86400,
                       "observed": len(chain), "quoted": sum(bool(q["quoted"]) for q in chain),
                       "atm_iv": atm, "put_minus_call_25d_iv": skew,
                       "gamma_oi_proxy": proxy if gamma else None,
                       "gamma_oi_units": "unverified venue gamma times OI; unsigned diagnostic only",
                       "oi_coverage": len(oi), "gamma_coverage": len(gamma),
                       "skew_instruments": [p25["instrument"], c25["instrument"]] if skew is not None else []})
    common_changes = []
    if previous is not None:
        if previous["received_at"] >= now:
            raise ValueError("future/duplicate previous surface")
        old = {q["instrument"]: q for q in previous["options"] if q.get("oi") is not None}
        for chain in groups.values():
            for q in chain:
                if q.get("oi") is not None and q["instrument"] in old:
                    common_changes.append(number(q["oi"]) - number(old[q["instrument"]]["oi"]))
    return {"status": "available" if tenors else "unavailable", "tenors": tenors,
            "rejected": rejected, "common_oi_changes": len(common_changes),
            "common_oi_delta": sum(common_changes) if common_changes else None,
            "signed_gex": None, "dealer_positioning": "unknown",
            "iv_source": "observed venue mark IV; ATM/skew require qualified L1 quotes"}
