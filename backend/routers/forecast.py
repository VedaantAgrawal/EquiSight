from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from schemas import ForecastSeries

router = APIRouter()


@router.get("/api/forecast/{symbol}", response_model=ForecastSeries)
async def get_forecast(symbol: str, session: AsyncSession = Depends(get_session)):
    symbol = symbol.upper()
    result = await session.execute(
        text(
            """
            SELECT date, actual, arima_pred, xgb_pred
            FROM forecast_points
            WHERE symbol = :symbol
            ORDER BY date
            """
        ),
        {"symbol": symbol},
    )
    rows = result.all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No forecast data for symbol '{symbol}'")

    return ForecastSeries(
        symbol=symbol,
        dates=[str(r[0]) for r in rows],
        actual=[r[1] for r in rows],
        arima_pred=[r[2] for r in rows],
        xgb_pred=[r[3] for r in rows],
    )
