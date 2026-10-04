"""Offline-only candidate controller. Not a production Condor profile.

The baseline's entry quality, accounts, depth, risk and venue checks are reused.
Candidate selection never mutates configs or a live executor registry.
"""
from copy import deepcopy

from agents.condor_agent import decide
from controllers.directional_trading.flyby import DeriveCesfLongVolController
from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction
from src.signal.return_model import predict_return, validate_model
from src.signal.optimization import expected_edge_allows, holding_exit

VARIANTS = ("baseline", "hold_only", "alpha_only", "combined")


class FlybyCandidateController(DeriveCesfLongVolController):
    def __init__(self, config, provider, queue, *, model=None, variant="combined"):
        if getattr(provider, "flyby_offline_replay", False) is not True:
            raise ValueError("candidate_controller_requires_explicit_offline_fixture")
        if variant not in VARIANTS or config.interval != "5m" or config.strategy_profile != "baseline":
            raise ValueError("candidate_requires_fixed_baseline_5m")
        if variant in ("alpha_only", "combined"):
            validate_model(model)
            if model["market"] != config.trading_pair.split("-")[0]:
                raise ValueError("candidate_model_market_mismatch")
        self.return_model, self.variant, self.return_estimate = deepcopy(model), variant, None
        super().__init__(config, provider, queue)

    async def update_processed_data(self):
        await super().update_processed_data()
        self.return_estimate = None
        if self.variant in ("alpha_only", "combined") and not self.processed_data.get("halt"):
            try:
                self.return_estimate = predict_return(self.return_model, self.processed_data,
                                                     self.processed_data["signal_time"] + 300)
                e = self.return_estimate
                self.processed_data["candidate_alpha"] = {"expected_gross_return": e.gross_return,
                    "noise_margin": e.noise_margin, "in_distribution": e.in_distribution,
                    "horizon_seconds": 1800, "confidence_is_probability": False, "live_authorized": False}
            except (ValueError, TypeError, KeyError):
                self.processed_data["candidate_alpha"] = {"status": "unavailable", "live_authorized": False}

    def entry_risk_weight(self, data):
        return .70 if self.variant == "combined" else super().entry_risk_weight(data)

    def additional_entry_gate(self, data, round_trip_cost):
        return self.variant not in ("alpha_only", "combined") or expected_edge_allows(
            self.return_estimate, data["signal"], round_trip_cost, data["risk_mode"] == "restricted")

    def stop_actions_proposal(self):
        # Always run parent account/hard-stop/timeout handling, including on error.
        proposals = super().stop_actions_proposal()
        if self.variant not in ("hold_only", "combined") or self.processed_data.get("halt") or self.config.manual_kill_switch:
            return proposals
        decision = decide(self.processed_data, active=self.config.condor_active)
        now = self.market_data_provider.time()
        out = []
        for executor in self.executors_info:
            if not executor.is_active:
                continue
            side = 1 if executor.config.side == TradeType.BUY else -1
            reason = ("pending_entry_timeout" if not executor.is_trading and now - executor.timestamp >= 30 else
                      holding_exit(decision, self.processed_data, side, self.return_estimate)
                      if executor.is_trading else None)
            if reason:
                out.append(StopExecutorAction(controller_id=self.config.id, executor_id=executor.id))
        return out
