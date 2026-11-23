import cedarpy_sqlalchemy
import flask
from sqlalchemy import Engine

from examples.photos import library

photos = flask.Blueprint("photos", __name__)


def reader() -> cedarpy_sqlalchemy.Reader[library.Photo]:
    # Verified by outer WSGI authentication. Never take this ID from a header.
    user_id = flask.request.remote_user
    if not user_id:
        flask.abort(401)
    store: cedarpy_sqlalchemy.Store[library.Photo] = flask.current_app.extensions[
        "photo_store"
    ]
    return store.for_user(user_id)


@photos.get("/photos/<photo_id>")
def photo(photo_id: str):
    found = reader().get(photo_id)
    if found is None:
        flask.abort(404)
    return {"id": found.id}


@photos.get("/photos")
def gallery():
    page = reader().page(limit=2, after=flask.request.args.get("after"))
    return {
        "ids": [item.id for item in page.items],
        "next_cursor": page.next_cursor,
    }


def create_app(engine: Engine) -> flask.Flask:
    app = flask.Flask(__name__)
    app.extensions["photo_store"] = library.photo_store(engine)
    app.register_blueprint(photos)
    return app
