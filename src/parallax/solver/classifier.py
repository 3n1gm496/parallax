from __future__ import annotations

from parallax.shared.schemas import IdentityResolutionStatus, ProofObject


class FalseArbitrageClassifier:
    def classify(
        self,
        *,
        identity_status: IdentityResolutionStatus,
        proof: ProofObject,
        displayed_edge: float,
        executable_edge: float,
        executable_pricing_used: bool,
    ) -> str | None:
        if identity_status != IdentityResolutionStatus.VERIFIED:
            return "identity_blocked"
        if displayed_edge > 0 and executable_edge <= 0:
            return "midpoint_only"
        if proof.proof_status in {"needs_review", "false_arbitrage"}:
            return "proof_needs_review"
        if not executable_pricing_used and proof.executable_pricing_used:
            return "execution_data_ignored"
        return None
