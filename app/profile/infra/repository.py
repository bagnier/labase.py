import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.profile.domain.models import Profile, ProfileCreate, ProfileUpdate
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

    async def update(self, profile: Profile, data: ProfileUpdate) -> Profile:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, field, value)
        profile.updated_at = datetime.now(UTC)
        self.session.add(profile)
        return profile
