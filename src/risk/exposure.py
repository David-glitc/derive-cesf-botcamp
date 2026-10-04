"""Explicit exposure identities; wider caps never imply a wider loss budget."""
BASELINE_EXPOSURE = "baseline"
ETH_EXPOSURE_TEST = "eth_exposure_40_75_v1"


def exposure_limits(profile=BASELINE_EXPOSURE, underlying=None):
    if profile == BASELINE_EXPOSURE:
        return {"perp_notional": .30, "perp_gross": .30, "option_net": .20, "option_gross": .30}
    if profile == ETH_EXPOSURE_TEST and underlying == "ETH":
        return {"perp_notional": .40, "perp_gross": .40, "option_net": .20, "option_gross": .75}
    raise ValueError("unapproved_exposure_profile_or_underlying")
