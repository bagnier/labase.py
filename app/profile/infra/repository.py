import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profile.domain.models import Profile, ProfileCreate, ProfileUpdate


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, profile_id: uuid.UUID) -> Profile | None:
        return await self.session.get(Profile, profile_id)

    async def get_by_auth_user_id(self, auth_user_id: uuid.UUID) -> Profile | None:
        result = await self.session.execute(
            select(Profile).where(Profile.auth_user_id == auth_user_id)
        )
        return result.scalars().first()

    async def get_by_email(self, email: str) -> Profile | None:
        result = await self.session.execute(select(Profile).where(Profile.email == email))
        return result.scalars().first()

    async def create(self, data: ProfileCreate) -> Profile:
        profile = Profile(**data.model_dump())
        self.session.add(profile)
        await self.session.commit()
        return profile

    async def update(self, profile: Profile, data: ProfileUpdate) -> Profile:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, field, value)
        profile.updated_at = datetime.now(UTC)
        self.session.add(profile)
        await self.session.commit()
        return profile

    async def delete(self, profile: Profile) -> None:
        await self.session.delete(profile)
        await self.session.commit()
