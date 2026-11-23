from contextlib import contextmanager

from sqlalchemy import create_engine, insert, update

from examples.photos import check, library, web


@contextmanager
def photo_database():
    engine = create_engine("sqlite://")
    try:
        library.Photo.__table__.create(engine)
        yield engine
    finally:
        engine.dispose()


def test_gallery_matches_concrete_cedar_and_observes_visibility_changes():
    rows = [
        ("1", "alice", "private"),
        ("2", "bob", "private"),
        ("3", "bob", "public"),
        ("4", "bob", "private"),
        ("5", "alice", "private"),
    ]
    with photo_database() as engine:
        with engine.begin() as db:
            db.execute(
                insert(library.Photo),
                [{"id": i, "owner_id": o, "visibility": v} for i, o, v in rows],
            )
        client = web.create_app(engine).test_client()
        auth = {"REMOTE_USER": "alice"}
        expected = [i for i, o, v in rows if check.can_view("alice", i, o, v)]
        assert expected == ["1", "3", "5"]
        for path in ("/photos", "/photos/1"):
            assert client.get(path, headers={"Remote-User": "alice"}).status_code == 401
        for i, _, _ in rows:
            assert client.get(f"/photos/{i}", environ_overrides=auth).status_code == (
                200 if i in expected else 404
            )
        first = client.get("/photos", environ_overrides=auth).get_json()
        second = client.get(
            "/photos",
            query_string={"after": first["next_cursor"]},
            environ_overrides=auth,
        ).get_json()
        assert first["ids"] == expected[:2]
        assert second == {"ids": expected[2:], "next_cursor": None}
        with engine.begin() as db:
            db.execute(
                update(library.Photo)
                .where(library.Photo.id == "3")
                .values(visibility="private")
            )
        # A later job uses the exact same reader, not the HTTP response as a grant.
        photos = library.photo_store(engine).for_user("alice")
        assert photos.get("3") is None
        assert [p.id for p in photos.page(limit=10).items] == ["1", "5"]


def test_photo_store_is_per_app_and_identity_is_per_request():
    with photo_database() as first_db, photo_database() as second_db:
        with first_db.begin() as db:
            db.execute(
                insert(library.Photo).values(
                    id="1", owner_id="alice", visibility="private"
                )
            )
        first = web.create_app(first_db).test_client()
        second = web.create_app(second_db).test_client()
        alice = {"REMOTE_USER": "alice"}
        assert first.get("/photos/1", environ_overrides=alice).get_json() == {"id": "1"}
        assert (
            first.get("/photos/1", environ_overrides={"REMOTE_USER": "bob"}).status_code
            == 404
        )
        assert second.get("/photos/1", environ_overrides=alice).status_code == 404
        assert second.get("/photos", environ_overrides=alice).get_json() == {
            "ids": [],
            "next_cursor": None,
        }
