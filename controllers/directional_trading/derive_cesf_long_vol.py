"""Compatibility import for the canonical Flyby controller.

Keep the historical Hummingbot controller name working while ensuring there
is only one implementation and one set of capability-gated defaults.
"""

try:
    from .flyby import DeriveCesfLongVolConfig, DeriveCesfLongVolController
except ImportError:  # Hummingbot may load the controller directory directly.
    from flyby import DeriveCesfLongVolConfig, DeriveCesfLongVolController

__all__ = ["DeriveCesfLongVolConfig", "DeriveCesfLongVolController"]
