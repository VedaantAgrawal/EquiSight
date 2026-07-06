from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from schemas import ComparisonSummary, SymbolMetrics

router = APIRouter()


@router.get("/api/metrics", response_model=ComparisonSummary)
async def get_comparison_summary(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        text(
            """
            SELECT n_symbols, mean_arima_rmse, mean_xgb_rmse, pct_rmse_improvement,
                   xgb_wins, wilcoxon_statistic, p_value, significant_at_0_05, updated_at
            FROM comparison_summary WHERE id = 1
            """
        )
    )
    row = result.one()
    return ComparisonSummary(
        n_symbols=row[0],
        mean_arima_rmse=row[1],
        mean_xgb_rmse=row[2],
        pct_rmse_improvement=row[3],
        xgb_wins=row[4],
        wilcoxon_statistic=row[5],
        p_value=row[6],
        significant_at_0_05=row[7],
        updated_at=str(row[8]),
    )


@router.get("/api/metrics/symbols", response_model=list[SymbolMetrics])
async def get_symbol_metrics(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        text(
            """
            SELECT symbol, arima_order, arima_rmse, xgb_rmse, adf_statistic,
                   adf_p_value, adf_stationary, ljung_box_p_value, ljung_box_white_noise
            FROM model_metrics ORDER BY symbol
            """
        )
    )
    return [
        SymbolMetrics(
            symbol=r[0],
            arima_order=r[1],
            arima_rmse=r[2],
            xgb_rmse=r[3],
            adf_statistic=r[4],
            adf_p_value=r[5],
            adf_stationary=r[6],
            ljung_box_p_value=r[7],
            ljung_box_white_noise=r[8],
        )
        for r in result.all()
    ]
