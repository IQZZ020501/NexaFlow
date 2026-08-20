from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.system_log import SystemLog as SystemLogEntity
from app.infrastructure.repositories.mapping import to_entity
from app.infrastructure.system_log import SystemLog


async def list_system_logs(
    db: AsyncSession,
    limit: int,
    offset: int = 0,
    *,
    level: str | None = None,
    event: str | None = None,
    status_code: int | None = None,
    user_id: str | None = None,
    search: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[SystemLogEntity]:
    """
    Retrieve system logs with pagination and optional filtering criteria.
    
    Parameters:
        limit (int): Maximum number of logs to return.
        offset (int): Number of logs to skip before collecting results.
        level (str | None): Log level to filter by.
        event (str | None): Event name to filter by.
        status_code (int | None): HTTP status code to filter by.
        user_id (str | None): User identifier to filter by.
        search (str | None): Case-insensitive text to search for in event, message, path, or username.
        from_date (datetime | None): Inclusive lower bound for the log creation date.
        to_date (datetime | None): Exclusive upper bound for the log creation date.
    
    Returns:
        list[SystemLogEntity]: Matching logs ordered from newest to oldest.
    """
    statement = select(SystemLog)
    if level:
        statement = statement.where(SystemLog.level == level)
    if event:
        statement = statement.where(SystemLog.event == event)
    if status_code is not None:
        statement = statement.where(SystemLog.status_code == status_code)
    if user_id:
        statement = statement.where(SystemLog.user_id == user_id)
    if search:
        pattern = f"%{search}%"
        statement = statement.where(
            or_(
                SystemLog.event.ilike(pattern),
                SystemLog.message.ilike(pattern),
                SystemLog.path.ilike(pattern),
                SystemLog.username.ilike(pattern),
            )
        )
    if from_date:
        statement = statement.where(SystemLog.created_at >= from_date)
    if to_date:
        statement = statement.where(SystemLog.created_at < to_date)
    result = await db.scalars(
        statement
        .order_by(SystemLog.created_at.desc(), SystemLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(SystemLogEntity, row) for row in result.all()]
