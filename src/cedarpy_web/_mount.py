import re

from cedarpy_web import Permission


def validate_mount(permission: Permission, challenge: str, **callbacks: object) -> None:
    if not isinstance(permission, Permission):
        raise TypeError("permission must be a Permission")
    for name, callback in callbacks.items():
        if not callable(callback):
            raise TypeError(f"{name} must be callable")
    # HTTP field content: visible bytes (including obs-text), with spaces
    # and horizontal tabs allowed only between them. Both adapters use Latin-1.
    if (
        not isinstance(challenge, str)
        or challenge.strip(" \t") != challenge
        or not re.fullmatch(r"[\t\x20-\x7e\x80-\xff]+", challenge)
    ):
        raise ValueError("challenge must be a nonempty HTTP header value")
