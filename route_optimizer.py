"""
StableBridge — Route Optimizer Service
=======================================
Core engine that calculates the cheapest Fiat → Stablecoin → Fiat path
for cross-border remittances.

Architecture:
  1. Fetch live FX rates from the Oracle Aggregator (simulated here).
  2. Fetch on-ramp / off-ramp fees per provider.
  3. Fetch chain gas + finality data per supported L1/L2.
  4. Enumerate all (stablecoin × chain × ramp) combinations.
  5. Score each candidate route on cost, speed, and reliability.
  6. Return the optimal route + ranked alternatives.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from itertools import product
from typing import Optional

from models import (
    Chain,
    ChainFee,
    FXRate,
    OptimalRoute,
    RampFee,
    RampProvider,
    RouteHop,
    RouteRequest,
    RouteStatus,
    RouteSummary,
    Stablecoin,
)

logger = logging.getLogger("stablebridge.route_optimizer")

# ────────────────────────────────────────────────────────────────
# Simulated Data Sources (replace with real API calls in prod)
# ────────────────────────────────────────────────────────────────

# In production these would be live calls to the FX Oracle Aggregator,
# Circle/Paxos APIs, and chain RPC nodes.

_FX_RATES: dict[str, float] = {
    "USD/INR": 84.50,
    "USD/PHP": 56.20,
    "USD/NGN": 1550.00,
    "USD/GBP": 0.79,
    "USD/EUR": 0.92,
    "USD/MXN": 17.15,
    "USD/BRL": 5.05,
    "USD/KES": 129.50,
    "USD/GHS": 14.80,
    "USD/PKR": 278.50,
}

_ON_RAMP_FEES: dict[RampProvider, RampFee] = {
    RampProvider.CIRCLE: RampFee(
        provider=RampProvider.CIRCLE,
        fee_percent=0.003,         # 0.30%
        flat_fee_usd=0.0,
        min_amount_usd=5.0,
        max_amount_usd=500_000.0,
        settlement_seconds=5.0,
    ),
    RampProvider.PAXOS: RampFee(
        provider=RampProvider.PAXOS,
        fee_percent=0.0035,        # 0.35%
        flat_fee_usd=0.0,
        min_amount_usd=10.0,
        max_amount_usd=250_000.0,
        settlement_seconds=8.0,
    ),
}

_OFF_RAMP_FEES: dict[str, RampFee] = {
    # Keyed by destination country code
    "IN": RampFee(
        provider=RampProvider.LOCAL_PSP,
        fee_percent=0.0015,        # 0.15%
        flat_fee_usd=0.0,
        settlement_seconds=10.0,
    ),
    "PH": RampFee(
        provider=RampProvider.LOCAL_PSP,
        fee_percent=0.002,
        flat_fee_usd=0.10,
        settlement_seconds=15.0,
    ),
    "NG": RampFee(
        provider=RampProvider.LOCAL_PSP,
        fee_percent=0.003,
        flat_fee_usd=0.25,
        settlement_seconds=20.0,
    ),
    "GB": RampFee(
        provider=RampProvider.WISE,
        fee_percent=0.001,
        flat_fee_usd=0.0,
        settlement_seconds=5.0,
    ),
    "MX": RampFee(
        provider=RampProvider.LOCAL_PSP,
        fee_percent=0.002,
        flat_fee_usd=0.15,
        settlement_seconds=12.0,
    ),
}

_CHAIN_FEES: dict[Chain, ChainFee] = {
    Chain.POLYGON_POS: ChainFee(
        chain=Chain.POLYGON_POS,
        gas_fee_usd=0.01,
        finality_seconds=24.0,     # 12 blocks × 2s
        confirmations_required=12,
        congestion_level=0.15,
    ),
    Chain.POLYGON_ZKEVM: ChainFee(
        chain=Chain.POLYGON_ZKEVM,
        gas_fee_usd=0.05,
        finality_seconds=600.0,    # ZK proof batch ~10 min
        confirmations_required=1,
        congestion_level=0.05,
    ),
    Chain.SOLANA: ChainFee(
        chain=Chain.SOLANA,
        gas_fee_usd=0.00025,
        finality_seconds=12.8,     # 32 slots × 0.4s
        confirmations_required=32,
        congestion_level=0.20,
    ),
    Chain.STELLAR: ChainFee(
        chain=Chain.STELLAR,
        gas_fee_usd=0.00001,
        finality_seconds=5.0,
        confirmations_required=1,
        congestion_level=0.02,
    ),
}

# Which stablecoins are available on which chains
_STABLECOIN_CHAINS: dict[Stablecoin, list[Chain]] = {
    Stablecoin.USDC: [
        Chain.POLYGON_POS,
        Chain.POLYGON_ZKEVM,
        Chain.SOLANA,
        Chain.STELLAR,
    ],
    Stablecoin.PYUSD: [
        Chain.POLYGON_POS,
        Chain.SOLANA,
    ],
}

# Stablecoin peg prices (1.0 = perfect peg)
_STABLECOIN_PEGS: dict[Stablecoin, float] = {
    Stablecoin.USDC: 1.0000,
    Stablecoin.PYUSD: 0.9998,
}

# De-peg circuit breaker thresholds
_DEPEG_YELLOW = 0.005
_DEPEG_ORANGE = 0.010
_DEPEG_RED = 0.020


# ────────────────────────────────────────────────────────────────
# Route Optimizer Engine
# ────────────────────────────────────────────────────────────────

class RouteOptimizer:
    """
    Calculates the cheapest Fiat → Stablecoin (on-chain) → Fiat route.

    Scoring formula (lower = better):
        score = (w_cost × total_fee_pct) + (w_speed × time_norm) + (w_risk × risk_score)

    Weights are tuned by the user's `preferred_speed` setting.
    """

    SPEED_WEIGHTS: dict[str, tuple[float, float, float]] = {
        #                   cost   speed   risk
        "cheapest":        (0.70,  0.15,   0.15),
        "balanced":        (0.45,  0.35,   0.20),
        "fastest":         (0.15,  0.70,   0.15),
    }

    MAX_TOTAL_SECONDS = 60.0   # Hard cap — reject routes over 60s

    def __init__(self) -> None:
        self._start_time = time.monotonic()

    # ── Public API ─────────────────────────────────────────────

    async def find_optimal_route(self, req: RouteRequest) -> OptimalRoute:
        """
        Main entry point. Enumerates candidates, scores them,
        and returns the best route with alternatives.
        """
        t0 = time.monotonic()

        # 1. Fetch live data (parallelized in production)
        fx_rate = await self._get_fx_rate(req.source_currency, req.destination_currency)
        on_ramp_fees = await self._get_on_ramp_fees()
        off_ramp_fee = await self._get_off_ramp_fee(req.recipient_country)
        chain_fees = await self._get_chain_fees()
        peg_prices = await self._get_peg_prices()

        if off_ramp_fee is None:
            return self._unavailable_route(req, "No off-ramp available for destination country")

        # 2. Enumerate all valid (stablecoin, chain, on_ramp) combos
        candidates: list[_CandidateRoute] = []

        for stablecoin, on_ramp_provider in product(Stablecoin, on_ramp_fees.keys()):
            # Check de-peg circuit breaker
            peg_deviation = abs(1.0 - peg_prices.get(stablecoin, 1.0))
            if peg_deviation > _DEPEG_ORANGE:
                logger.warning(
                    "Skipping %s — de-peg deviation %.4f exceeds ORANGE threshold",
                    stablecoin.value, peg_deviation,
                )
                continue

            available_chains = _STABLECOIN_CHAINS.get(stablecoin, [])
            for chain in available_chains:
                chain_fee = chain_fees.get(chain)
                on_ramp = on_ramp_fees[on_ramp_provider]
                if chain_fee is None:
                    continue

                candidate = self._build_candidate(
                    req=req,
                    stablecoin=stablecoin,
                    chain=chain,
                    on_ramp=on_ramp,
                    off_ramp=off_ramp_fee,
                    chain_fee=chain_fee,
                    fx_rate=fx_rate,
                    peg_deviation=peg_deviation,
                )

                if candidate is not None:
                    candidates.append(candidate)

        if not candidates:
            return self._unavailable_route(req, "No viable route found")

        # 3. Score and rank
        w_cost, w_speed, w_risk = self.SPEED_WEIGHTS[req.preferred_speed]
        for c in candidates:
            c.score = (
                w_cost * c.fee_percent
                + w_speed * (c.total_seconds / self.MAX_TOTAL_SECONDS)
                + w_risk * c.risk_score
            )

        candidates.sort(key=lambda c: c.score)
        best = candidates[0]

        # 4. Build response
        alternatives = [
            RouteSummary(
                stablecoin=c.stablecoin,
                chain=c.chain,
                total_fee_usd=c.fee_usd,
                total_fee_percent=round(c.fee_percent * 100, 4),
                estimated_seconds=c.total_seconds,
                destination_amount=c.dest_amount,
            )
            for c in candidates[1:4]   # Top 3 alternatives
        ]

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "Route optimized in %.1fms — best: %s on %s (%.2f%% fee, %.0fs)",
            elapsed_ms,
            best.stablecoin.value,
            best.chain.value,
            best.fee_percent * 100,
            best.total_seconds,
        )

        return OptimalRoute(
            status=self._determine_status(best),
            source_currency=req.source_currency,
            destination_currency=req.destination_currency,
            source_amount=req.amount,
            destination_amount=round(best.dest_amount, 2),
            total_fee_usd=round(best.fee_usd, 4),
            total_fee_percent=round(best.fee_percent * 100, 4),
            estimated_seconds=best.total_seconds,
            fx_rate_used=fx_rate.rate,
            stablecoin=best.stablecoin,
            chain=best.chain,
            hops=best.hops,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
            warnings=best.warnings,
            alternatives=alternatives,
        )

    # ── Candidate Builder ──────────────────────────────────────

    def _build_candidate(
        self,
        req: RouteRequest,
        stablecoin: Stablecoin,
        chain: Chain,
        on_ramp: RampFee,
        off_ramp: RampFee,
        chain_fee: ChainFee,
        fx_rate: FXRate,
        peg_deviation: float,
    ) -> Optional[_CandidateRoute]:
        """Build a single candidate route and calculate all costs."""

        warnings: list[str] = []

        # ── Step 1: On-Ramp (Fiat → Stablecoin) ───────────────
        on_ramp_fee_usd = req.amount * on_ramp.fee_percent + on_ramp.flat_fee_usd
        stablecoin_amount = req.amount - on_ramp_fee_usd

        if stablecoin_amount <= 0:
            return None

        hop1 = RouteHop(
            step=1,
            action="on_ramp",
            provider=on_ramp.provider.value,
            stablecoin=stablecoin,
            input_currency=req.source_currency,
            input_amount=req.amount,
            output_currency=stablecoin.value,
            output_amount=round(stablecoin_amount, 6),
            fee_usd=round(on_ramp_fee_usd, 4),
            estimated_seconds=on_ramp.settlement_seconds,
        )

        # ── Step 2: Chain Transfer ─────────────────────────────
        after_gas = stablecoin_amount - chain_fee.gas_fee_usd

        if after_gas <= 0:
            return None

        hop2 = RouteHop(
            step=2,
            action="chain_transfer",
            chain=chain,
            stablecoin=stablecoin,
            input_currency=stablecoin.value,
            input_amount=round(stablecoin_amount, 6),
            output_currency=stablecoin.value,
            output_amount=round(after_gas, 6),
            fee_usd=chain_fee.gas_fee_usd,
            estimated_seconds=chain_fee.finality_seconds,
        )

        # Congestion warning
        if chain_fee.congestion_level > 0.5:
            warnings.append(
                f"{chain.value} congestion at {chain_fee.congestion_level:.0%} — "
                f"may cause delays"
            )

        # ── Step 3: Off-Ramp (Stablecoin → Fiat) ──────────────
        off_ramp_fee_usd = after_gas * off_ramp.fee_percent + off_ramp.flat_fee_usd
        usd_equivalent = after_gas - off_ramp_fee_usd

        if usd_equivalent <= 0:
            return None

        dest_amount = usd_equivalent * fx_rate.rate

        hop3 = RouteHop(
            step=3,
            action="off_ramp",
            provider=off_ramp.provider.value,
            chain=chain,
            input_currency=stablecoin.value,
            input_amount=round(after_gas, 6),
            output_currency=req.destination_currency,
            output_amount=round(dest_amount, 2),
            fee_usd=round(off_ramp_fee_usd, 4),
            estimated_seconds=off_ramp.settlement_seconds,
        )

        # ── Totals ─────────────────────────────────────────────
        total_fee_usd = on_ramp_fee_usd + chain_fee.gas_fee_usd + off_ramp_fee_usd
        total_fee_pct = total_fee_usd / req.amount
        total_seconds = (
            on_ramp.settlement_seconds
            + chain_fee.finality_seconds
            + off_ramp.settlement_seconds
        )

        # Reject routes that exceed 60s hard cap (unless user wants cheapest)
        if total_seconds > self.MAX_TOTAL_SECONDS and req.preferred_speed != "cheapest":
            return None

        if total_seconds > self.MAX_TOTAL_SECONDS:
            warnings.append(
                f"Route exceeds 60s target ({total_seconds:.0f}s) — "
                f"selected for lowest cost"
            )

        # De-peg yellow warning
        if peg_deviation > _DEPEG_YELLOW:
            warnings.append(
                f"{stablecoin.value} peg deviation at {peg_deviation:.2%} — "
                f"YELLOW alert active"
            )

        # Risk score: combines congestion + de-peg deviation
        risk_score = (
            chain_fee.congestion_level * 0.4
            + (peg_deviation / _DEPEG_ORANGE) * 0.6
        )

        return _CandidateRoute(
            stablecoin=stablecoin,
            chain=chain,
            fee_usd=total_fee_usd,
            fee_percent=total_fee_pct,
            total_seconds=total_seconds,
            dest_amount=dest_amount,
            hops=[hop1, hop2, hop3],
            risk_score=min(risk_score, 1.0),
            warnings=warnings,
            score=0.0,   # Will be computed during ranking
        )

    # ── Data Fetchers (simulated) ──────────────────────────────

    async def _get_fx_rate(self, src: str, dst: str) -> FXRate:
        """Fetch FX rate from Oracle Aggregator."""
        pair = f"{src}/{dst}"
        rate = _FX_RATES.get(pair)
        if rate is None:
            raise ValueError(f"Unsupported currency pair: {pair}")
        return FXRate(
            pair=pair,
            rate=rate,
            source="oracle_aggregator",
            confidence=0.98,
            timestamp=datetime.now(timezone.utc),
        )

    async def _get_on_ramp_fees(self) -> dict[RampProvider, RampFee]:
        return _ON_RAMP_FEES

    async def _get_off_ramp_fee(self, country: str) -> Optional[RampFee]:
        return _OFF_RAMP_FEES.get(country)

    async def _get_chain_fees(self) -> dict[Chain, ChainFee]:
        return _CHAIN_FEES

    async def _get_peg_prices(self) -> dict[Stablecoin, float]:
        return _STABLECOIN_PEGS

    # ── Helpers ────────────────────────────────────────────────

    def _determine_status(self, best: _CandidateRoute) -> RouteStatus:
        if best.warnings:
            return RouteStatus.SUBOPTIMAL
        if best.fee_percent > 0.01:   # > 1% fee
            return RouteStatus.DEGRADED
        return RouteStatus.OPTIMAL

    def _unavailable_route(self, req: RouteRequest, reason: str) -> OptimalRoute:
        return OptimalRoute(
            status=RouteStatus.UNAVAILABLE,
            source_currency=req.source_currency,
            destination_currency=req.destination_currency,
            source_amount=req.amount,
            destination_amount=0.0,
            total_fee_usd=0.0,
            total_fee_percent=0.0,
            estimated_seconds=0.0,
            fx_rate_used=0.0,
            stablecoin=Stablecoin.USDC,
            chain=Chain.POLYGON_POS,
            hops=[],
            expires_at=datetime.now(timezone.utc),
            warnings=[reason],
        )


# ────────────────────────────────────────────────────────────────
# Internal candidate dataclass
# ────────────────────────────────────────────────────────────────

class _CandidateRoute:
    __slots__ = (
        "stablecoin", "chain", "fee_usd", "fee_percent",
        "total_seconds", "dest_amount", "hops", "risk_score",
        "warnings", "score",
    )

    def __init__(
        self,
        stablecoin: Stablecoin,
        chain: Chain,
        fee_usd: float,
        fee_percent: float,
        total_seconds: float,
        dest_amount: float,
        hops: list[RouteHop],
        risk_score: float,
        warnings: list[str],
        score: float,
    ):
        self.stablecoin = stablecoin
        self.chain = chain
        self.fee_usd = fee_usd
        self.fee_percent = fee_percent
        self.total_seconds = total_seconds
        self.dest_amount = dest_amount
        self.hops = hops
        self.risk_score = risk_score
        self.warnings = warnings
        self.score = score
