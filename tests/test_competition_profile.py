import unittest
from pathlib import Path

from agents.condor_agent import decide


ROOT = Path(__file__).resolve().parents[1]


class CompetitionProfileTests(unittest.TestCase):
    def test_live_script_contains_only_approved_profiles(self):
        text = (ROOT / "conf/scripts/conf_v2_flyby.yml").read_text()
        for name in ("conf_flyby_eth.yml", "conf_flyby_btc.yml", "conf_flyby_sol.yml", "conf_flyby_hype.yml"):
            self.assertIn(name, text)
        self.assertNotIn("conf_flyby_arb.yml", text)
        self.assertNotIn("conf_flyby_avax.yml", text)

    def test_live_profiles_disable_unverified_features(self):
        for name in ("eth", "btc", "sol", "hype"):
            text = (ROOT / f"conf/controllers/conf_flyby_{name}.yml").read_text()
            self.assertIn("options_enabled: false", text)
            self.assertIn("portfolio_margin: false", text)
            self.assertIn("spot_hedge_enabled: false", text)

    def test_condor_does_not_route_options_without_capability(self):
        decision = decide({"cesf_score": 0.45, "edge": 0.02, "svi_skew": 2.5, "ccy": "ETH"})
        self.assertEqual(decision.execution_venue, "derive-perp")
        self.assertEqual(decision.derive_instrument, "ETH-PERP")
        self.assertNotIn("derive-options", decision.reason)

    def test_condor_can_route_options_only_when_explicitly_capable(self):
        decision = decide(
            {"cesf_score": 0.45, "edge": 0.02, "svi_skew": 2.5, "ccy": "ETH", "options_capable": True}
        )
        self.assertEqual(decision.execution_venue, "derive-options")


if __name__ == "__main__":
    unittest.main()
