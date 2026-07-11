import uuid

from sqlalchemy import select

from apps.profile.domain.models import Profile, ProfileCreate, ProfileUpdate
from apps.shared.clock import now
from apps.shared.persistence.repository import BaseRepository
from apps.shared.slug_registry import handle_is_available, slugify, unique_handle


class ProfileRepository(BaseRepository[Profile]):
    model = Profile

    async def get_by_auth_user_id(self, auth_user_id: uuid.UUID) -> Profile | None:
        return await self.session.scalar(
            select(Profile).where(Profile.auth_user_id == auth_user_id)
        )

    async def get_by_email(self, email: str) -> Profile | None:
        return await self.session.scalar(select(Profile).where(Profile.email == email))

    async def get_with_auto_handle(
        self, auth_user_id: uuid.UUID, email: str, handle_enabled: bool
    ) -> Profile | None:
        """Load the profile and, if it still lacks a handle, mint one when handles are on."""
        profile = await self.get_by_auth_user_id(auth_user_id)
        if profile is not None and profile.handle is None and handle_enabled:
            profile = await self.auto_handle(profile, email)
        return profile

    async def get_or_create(self, auth_user_id: uuid.UUID, email: str) -> Profile:
        profile = await self.get_by_auth_user_id(auth_user_id)
        if profile is None:
            profile = await self.create(ProfileCreate(auth_user_id=auth_user_id, email=email))
        return profile

    async def create(self, data: ProfileCreate) -> Profile:
        profile = Profile(**data.model_dump())
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def auto_handle(self, profile: Profile, email: str) -> Profile:
        """Derive a unique URL-safe handle from the email prefix and persist it."""
        base = slugify(email.split("@")[0]) or "user"
        handle = await unique_handle(
            base, self.session, exclude_from="profiles", exclude_id=profile.id
        )
        profile.handle = handle
        profile.updated_at = now()
        self.session.add(profile)
        return profile

    async def is_handle_available(self, handle: str, profile_id: uuid.UUID) -> bool:
        return await handle_is_available(
            handle, self.session, exclude_from="profiles", exclude_id=profile_id
        )

    async def update(self, profile: Profile, data: ProfileUpdate) -> Profile:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, field, value)
        profile.updated_at = now()
        self.session.add(profile)
        return profile
