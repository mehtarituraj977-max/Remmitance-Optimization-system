"""
StableBridge — Pydantic models for the Route Optimizer service.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enumerations ────────────────────────────────────────────────

class Chain(str, Enum):
    POLYGON_POS = "polygon_pos"
    POLYGON_ZKEVM = "polygon_zkevm"
    SOLANA = "solana"
    STELLAR = "stellar"


class Stablecoin(str, Enum):
    USDC = "USDC"
    PYUSD = "PYUSD"


class RampProvider(str, Enum):
    CIRCLE = "circle"
    PAXOS = "paxos"
    WISE = "wise"
    LOCAL_PSP = "local_psp"


class RouteStatus(str, Enum):
    OPTIMAL = "optimal"
    SUBOPTIMAL = "suboptimal"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


# ── Rate & Fee Structures ──────────────────────────────────────

class FXRate(BaseModel):
    pair: str                             # e.g. "USD/INR"
    rate: float
    source: str                           # "binance", "chainlink", etc.
    confidence: float = Field(ge=0, le=1)
    timestamp: datetime
    stale: bool = False


class ChainFee(BaseModel):
    chain: Chain
    gas_fee_usd: float                    # Estimated gas in USD
    finality_seconds: float               # Expected time to finality
    confirmations_required: int
    congestion_level: float = Field(ge=0, le=1, default=0.0)


class RampFee(BaseModel):
    provider: RampProvider
    fee_percent: float                    # e.g. 0.003 = 0.3%
    flat_fee_usd: float = 0.0
    min_amount_usd: float = 1.0
    max_amount_usd: float = 1_000_000.0
    settlement_seconds: float             # Expected settlement time


# ── Route Structures ───────────────────────────────────────────

class RouteHop(BaseModel):
    """One leg of the full Fiat→Crypto→Fiat route."""
    step: int
    action: str                           # "on_ramp", "chain_transfer", "off_ramp"
    provider: Optional[str] = None
    chain: Optional[Chain] = None
    stablecoin: Optional[Stablecoin] = None
    input_currency: str
    input_amount: float
    output_currency: str
    output_amount: float
    fee_usd: float
    estimated_seconds: float


class OptimalRoute(BaseModel):
    """The full optimized route returned by the service."""
    route_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: RouteStatus
    source_currency: str
    destination_currency: str
    source_amount: float
    destination_amount: float
    total_fee_usd: float
    total_fee_percent: float
    estimated_seconds: float
    fx_rate_used: float
    stablecoin: Stablecoin
    chain: Chain
    hops: list[RouteHop]
    expires_at: datetime
    warnings: list[str] = []
    alternatives: list[RouteSummary] = []


class RouteSummary(BaseModel):
    """Compact summary of an alternative route."""
    stablecoin: Stablecoin
    chain: Chain
    total_fee_usd: float
    total_fee_percent: float
    estimated_seconds: float
    destination_amount: float


# ── API Request / Response ─────────────────────────────────────

class RouteRequest(BaseModel):
    source_currency: str = Field(
        ..., min_length=3, max_length=3, examples=["USD"]
    )
    destination_currency: str = Field(
        ..., min_length=3, max_length=3, examples=["INR"]
    )
    amount: float = Field(..., gt=0, le=1_000_000, examples=[100.0])
    sender_country: str = Field(
        ..., min_length=2, max_length=2, examples=["US"]
    )
    recipient_country: str = Field(
        ..., min_length=2, max_length=2, examples=["IN"]
    )
    preferred_speed: str = Field(
        default="balanced",
        pattern="^(fastest|balanced|cheapest)$",
    )
    idempotency_key: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    active_corridors: int
    fx_oracle_ok: bool
    chains_ok: dict[str, bool]
