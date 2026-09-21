"""Profile endpoints: multiple profiles, one active at a time.

The active profile is applied to every request automatically by the prompt
builder, so switching profiles changes the next answer without a restart.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import get_memory_service
from backend.profile.models import (
    ProfileDuplicateRequest,
    UserProfile,
    UserProfileCreate,
    UserProfileList,
    UserProfilePatch,
    UserProfileUpdate,
)
from backend.services.memory_service import MemoryService
from backend.utils.errors import NotFoundError

router = APIRouter(tags=["profile"])


# --------------------------------------------------------------- collection
@router.get("/api/profiles", response_model=UserProfileList)
async def list_profiles(
    service: MemoryService = Depends(get_memory_service),
) -> UserProfileList:
    """All profiles plus the id of the active one."""
    return service.list_profiles()


@router.post("/api/profiles", response_model=UserProfile, status_code=201)
async def create_profile(
    payload: UserProfileCreate,
    service: MemoryService = Depends(get_memory_service),
) -> UserProfile:
    """Create a profile. The first profile created becomes active."""
    return service.create_profile(payload)


# ------------------------------------------------------------------- single
@router.get("/api/profiles/{profile_id}", response_model=UserProfile)
async def get_profile(
    profile_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> UserProfile:
    profile = service.get_profile(profile_id)
    if not profile.exists:
        raise NotFoundError("Профиль не найден.")
    return profile


@router.put("/api/profiles/{profile_id}", response_model=UserProfile)
async def update_profile(
    profile_id: str,
    payload: UserProfilePatch,
    service: MemoryService = Depends(get_memory_service),
) -> UserProfile:
    """Update name, description and/or settings of one profile."""
    return service.update_profile(profile_id, payload)


@router.delete("/api/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> None:
    """Delete a profile.

    Refused with 409 when it is the active profile or the last remaining one.
    """
    service.delete_profile(profile_id)


@router.post("/api/profiles/{profile_id}/activate", response_model=UserProfile)
async def activate_profile(
    profile_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> UserProfile:
    """Make this profile active. Exactly one profile is active at a time."""
    return service.activate_profile(profile_id)


@router.post(
    "/api/profiles/{profile_id}/duplicate",
    response_model=UserProfile,
    status_code=201,
)
async def duplicate_profile(
    profile_id: str,
    payload: Optional[ProfileDuplicateRequest] = None,
    service: MemoryService = Depends(get_memory_service),
) -> UserProfile:
    """Copy a profile under a new name. The copy is not activated."""
    return service.duplicate_profile(profile_id, payload)


# ------------------------------------------------------- active profile view
@router.get("/api/profile/active", response_model=UserProfile)
async def read_active_profile(
    service: MemoryService = Depends(get_memory_service),
) -> UserProfile:
    """The profile currently applied to requests."""
    return service.get_active_profile()


@router.get("/api/profile/prompt-block")
async def profile_prompt_block(
    profile_id: Optional[str] = Query(default=None),
    service: MemoryService = Depends(get_memory_service),
) -> dict:
    """The exact profile text injected into the system prompt."""
    resolved = profile_id or service.profile.get_active_profile_id()
    return {
        "profile_id": resolved,
        "block": service.profile_prompt_block(resolved),
    }


# ------------------------------------------- legacy single-profile endpoints
@router.get("/api/profile", response_model=UserProfile)
async def read_profile(
    profile_id: Optional[str] = Query(default=None),
    service: MemoryService = Depends(get_memory_service),
) -> UserProfile:
    """The active profile (kept for backwards compatibility)."""
    return service.get_profile(profile_id)


@router.put("/api/profile", response_model=UserProfile)
async def update_active_profile(
    payload: UserProfileUpdate,
    profile_id: Optional[str] = Query(default=None),
    service: MemoryService = Depends(get_memory_service),
) -> UserProfile:
    """Update the active profile's settings."""
    return service.save_profile(payload, profile_id)


@router.delete("/api/profile", response_model=UserProfile)
async def reset_active_profile(
    profile_id: Optional[str] = Query(default=None),
    service: MemoryService = Depends(get_memory_service),
) -> UserProfile:
    """Reset a profile's settings to defaults (the profile itself is kept)."""
    return service.reset_profile(profile_id)