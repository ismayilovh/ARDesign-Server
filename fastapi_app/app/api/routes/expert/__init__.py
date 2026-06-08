"""Expert evaluation API.

Single authorization gate: the router-level `get_current_expert_user` dependency
applies to every sub-route, so no expert endpoint can ship ungated. Strictly
separate from the admin panel - only the EXPERT role reaches these routes.
"""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_expert_user
from app.api.routes.expert import submissions

router = APIRouter(
    prefix="/expert",
    tags=["expert"],
    dependencies=[Depends(get_current_expert_user)],
)
router.include_router(submissions.router)