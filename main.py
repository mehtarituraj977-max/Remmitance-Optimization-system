"""
StableBridge — Route Optimizer FastAPI Service
===============================================
Exposes the Route Optimizer engine as an HTTP API.

Run:
    uvicorn main:app --reload --port 8000

Try:
    curl -X POST http://localhost:8000/api/v1/routes/optimize \
      -H "Content-Type: application/json" \
      -d '{"source_currency":"USD","destination_currency":"INR","amount":100,"sender_country":"US","recipient_country":"IN"}'
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import HealthResponse, OptimalRoute, RouteRequest, RouteStatus
from route_optimizer import RouteOptimizer

# ── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-32s │ %(levelname)-5s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("stablebridge.api")

# ── Globals ─────────────────────────────────────────────────────
_optimizer: RouteOptimizer | None = None
_start_time: float = 0.0


# ── Lifespan ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _optimizer, _start_time
    _start_time = time.monotonic()
    _optimizer = RouteOptimizer()
    logger.info("✦ StableBridge Route Optimizer started")
    yield
    logger.info("✦ StableBridge Route Optimizer shutting down")


# ── App ─────────────────────────────────────────────────────────
app = FastAPI(
    title="StableBridge Route Optimizer",
    description=(
        "Calculates the cheapest Fiat → Stablecoin → Fiat path "
        "for cross-border remittances, optimizing across multiple "
        "chains (Polygon, Solana, Stellar) and stablecoins (USDC, PYUSD)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ──────────────────────────────────────────────────────

@app.post(
    "/api/v1/routes/optimize",
    response_model=OptimalRoute,
    summary="Find optimal remittance route",
    tags=["Routes"],
)
async def optimize_route(req: RouteRequest) -> OptimalRoute:
    """
    Given a source/destination currency, amount, and country pair,
    returns the optimal Fiat→Stablecoin→Fiat route with cost/speed breakdown.

    **Example:**  $100 USD → INR via USDC on Polygon PoS

    The response includes:
    - Hop-by-hop breakdown (on-ramp → chain transfer → off-ramp)
    - Total fee in USD and as a percentage
    - Estimated settlement time in seconds
    - Up to 3 alternative routes ranked by the selected preference
    - Active warnings (de-peg alerts, congestion, etc.)
    """
    try:
        result = await _optimizer.find_optimal_route(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Route optimization failed")
        raise HTTPException(status_code=500, detail="Internal routing error")

    if result.status == RouteStatus.UNAVAILABLE:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "no_route",
                "message": result.warnings[0] if result.warnings else "No route available",
            },
        )

    return result


@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
    summary="Service health check",
    tags=["Operations"],
)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        uptime_seconds=round(time.monotonic() - _start_time, 2),
        active_corridors=len(
            {
                pair.split("/")[1]
                for pair in [
                    "USD/INR", "USD/PHP", "USD/NGN",
                    "USD/GBP", "USD/MXN",
                ]
            }
        ),
        fx_oracle_ok=True,
        chains_ok={
            "polygon_pos": True,
            "polygon_zkevm": True,
            "solana": True,
            "stellar": True,
        },
    )


# ── Dev Runner ──────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
