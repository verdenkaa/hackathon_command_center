"""SSE invalidation feed. Works across workers and survives reconnects/restarts."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.db.models import PlanningState, User
from app.deps import get_current_user, get_db, require_member

router = APIRouter(tags=['realtime'])


async def project_events(request: Request, bind: Engine, project_id: int) -> AsyncIterator[str]:
    previous: int | None = None
    idle = 0
    while not await request.is_disconnected():
        def revision() -> int:
            # Never hold a connection/transaction for the lifetime of a stream.
            with Session(bind) as db:
                get_current_user(request, db)  # Also checks revocation and project access.
                state = db.get(PlanningState, project_id)
                return state.revision if state else 0
        try:
            current = await run_in_threadpool(revision)
        except HTTPException:
            yield 'event: access-lost\ndata: {}\n\n'
            return
        if current != previous:
            yield f'id: {current}\nevent: change\nretry: 1000\ndata: {{"revision":{current}}}\n\n'
            previous, idle = current, 0
        else:
            idle += 1
            if idle >= 60:
                yield ': keepalive\n\n'
                idle = 0
        await asyncio.sleep(0.25)


@router.get('/projects/{project_id}/events')
def events(project_id: int, request: Request, db: Session = Depends(get_db),
           _user: User = Depends(require_member)) -> StreamingResponse:
    bind = db.get_bind()
    db.close()
    return StreamingResponse(project_events(request, bind, project_id), media_type='text/event-stream',
                             headers={'Cache-Control':'no-cache', 'X-Accel-Buffering':'no'})
