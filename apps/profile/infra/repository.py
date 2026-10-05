import uuid

from sqlalchemy import select

from apps.profile.domain.models import Profile, ProfileCreate, ProfileUpdate
from apps.shared.integration.slugs import handle_is_available, slugify, unique_handle
from apps.shared.persistence.repository import BaseRepository


class ProfileRepository(BaseRepository[Profile]):
    model = Profile

    async def get_by_user_id(self, user_id: uuid.UUID) -> Profile | None:
        return await self.session.scalar(select(Profile).where(Profile.user_id == user_id))

    async def get_by_email(self, email: str) -> Profile | None:
        return await self.session.scalar(select(Profile).where(Profile.email == email))

    async def get_with_auto_handle(
        self, user_id: uuid.UUID, email: str, *, handle_enabled: bool
    ) -> Profile | None:
        """The profile, minting a handle if it has none and handles are on."""
        profile = await self.get_by_user_id(user_id)
        if profile is not None and profile.handle is None and handle_enabled:
            profile = await self.auto_handle(profile, email)
        return profile

    async def get_or_create(self, user_id: uuid.UUID, email: str) -> Profile:
        profile = await self.get_by_user_id(user_id)
        if profile is None:
            profile = await self.create(ProfileCreate(user_id=user_id, email=email))
        return profile

    async def create(self, data: ProfileCreate) -> Profile:
        profile = Profile(**data.model_dump())
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def auto_handle(self, profile: Profile, email: str) -> Profile:
        """A unique handle from the email prefix, persisted."""
        base = slugify(email.split("@", maxsplit=1)[0]) or "user"
        handle = await unique_handle(
            base, self.session, exclude_from="profiles", exclude_id=profile.id
        )
        profile.handle = handle
        self.session.add(profile)
        return profile

    async def set_avatar_path(self, profile: Profile, path: str) -> None:
        """Store the avatar path, flushed so the route's fact follows a visible row."""
        profile.avatar_path = path
        await self.session.flush()

    async def is_handle_available(self, handle: str, profile_id: uuid.UUID) -> bool:
        return await handle_is_available(
            handle, self.session, exclude_from="profiles", exclude_id=profile_id
        )

    async def update(self, profile: Profile, data: ProfileUpdate) -> Profile:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, field, value)
        self.session.add(profile)
        return profile
