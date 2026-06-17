import uuid

from sqlalchemy import select

from app.profile.domain.models import Profile, ProfileCreate, ProfileUpdate
from app.shared.clock import now
from app.shared.handle_service import handle_is_available, unique_handle
from app.shared.names import slugify
from app.shared.persistence.repository import BaseRepository


class ProfileRepository(BaseRepository[Profile]):
    model = Profile

    async def get_by_auth_user_id(self, auth_user_id: uuid.UUID) -> Profile | None:
        return await self.session.scalar(
            select(Profile).where(Profile.auth_user_id == auth_user_id)
        )

    async def get_by_email(self, email: str) -> Profile | None:
        return await self.session.scalar(select(Profile).where(Profile.email == email))

    async def create(self, data: ProfileCreate) -> Profile:
        profile = Profile(**data.model_dump())
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def auto_handle(self, profile: Profile, email: str) -> Profile:
        """Derive a unique URL-safe handle from the email prefix and persist it."""
        base = slugify(email.split("@")[0]) or "user"
        handle = await unique_handle(base, self.session, exclude_profile_id=profile.id)
        profile.handle = handle
        profile.updated_at = now()
        self.session.add(profile)
        return profile

    async def is_handle_available(self, handle: str, profile_id: uuid.UUID) -> bool:
        return await handle_is_available(handle, self.session, exclude_profile_id=profile_id)

    async def update(self, profile: Profile, data: ProfileUpdate) -> Profile:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, field, value)
        profile.updated_at = now()
        self.session.add(profile)
        return profile
