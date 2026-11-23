"""A CLI, Flask app or worker can import photo_store without importing a web framework."""

from cedarpy_sqlalchemy import CedarAuthorizationMixin, Store, attr, ref
from sqlalchemy import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from examples.photos import check


class Base(DeclarativeBase):
    pass


class Photo(Base, CedarAuthorizationMixin):
    __tablename__ = "photos"
    cedar_type = "Photo"

    id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(info=ref("owner", "User"))
    visibility: Mapped[str] = mapped_column(info=attr("visibility"))


def photo_store(engine: Engine) -> Store[Photo]:
    return Store(
        engine, Photo, action="view", schema=check.SCHEMA, policies=check.POLICIES
    )
