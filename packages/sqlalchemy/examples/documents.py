"""Run after installing the SQL package, its async extra, and aiosqlite."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from cedarpy_sqlalchemy import AsyncStore, CedarAuthorizationMixin, Store, attr, ref
from sqlalchemy import create_engine, insert
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Document(Base, CedarAuthorizationMixin):
    __tablename__ = "documents"
    cedar_type = "Document"

    id: Mapped[str] = mapped_column(primary_key=True)
    state: Mapped[str] = mapped_column(info=attr("state"))
    owner_id: Mapped[str] = mapped_column(info=ref("owner", "User"))


schema = Path(__file__).with_suffix(".cedarschema")
source = Path(__file__).with_suffix(".cedar")


async def async_list(path: Path) -> list[str]:
    db = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        docs = AsyncStore(db, Document, policies=source, schema=schema).for_user(
            "alice"
        )
        return [doc.id for doc in (await docs.page(limit=10)).items]
    finally:
        await db.dispose()


if __name__ == "__main__":
    with TemporaryDirectory() as folder:
        path = Path(folder) / "demo.sqlite"
        db = create_engine(f"sqlite:///{path}")
        try:
            with db.begin() as conn:
                Base.metadata.create_all(conn)
                conn.execute(
                    insert(Document),
                    [
                        {"id": i, "state": s, "owner_id": o}
                        for i, s, o in [
                            ("1", "draft", "alice"),
                            ("2", "sealed", "alice"),
                            ("3", "public", "bob"),
                        ]
                    ],
                )
            docs = Store(db, Document, policies=source, schema=schema).for_user("alice")
            print("sync:", [doc.id for doc in docs.page(limit=10).items])
        finally:
            db.dispose()
        print("async:", asyncio.run(async_list(path)))
