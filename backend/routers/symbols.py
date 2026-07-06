from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session

router = APIRouter()


@router.get("/api/symbols", response_model=list[str])
async def list_symbols(session: AsyncSession = Depends(get_session)):
    result = await session.execute(text("SELECT symbol FROM model_metrics ORDER BY symbol"))
    return [row[0] for row in result.all()]
