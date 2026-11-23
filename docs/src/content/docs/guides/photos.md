---
title: Why a gallery and a photo URL need the same rule
---

Alice opens a gallery and sees photos `1`, `3`, and `5`. If she types `/photos/2` in the address bar, should she see that photo too? No. The permission is to **view a photo**, not to call a particular URL. Opening the gallery and opening one photo are two ways of asking the same question.

## Predict the two pages

Alice may view her own photos and anyone's public photos. Here is the whole gallery in ID order:

| ID | Owner | Visibility | Alice can view it? |
| --- | --- | --- | --- |
| 1 | Alice | Private | Yes, she owns it. |
| 2 | Bob | Private | No. |
| 3 | Bob | Public | Yes, it is public. |
| 4 | Bob | Private | No. |
| 5 | Alice | Private | Yes, she owns it. |

A page of size two should return `1, 3`, then `5`. If you fetch two database rows first and *then* remove Bob's private photo, you return only `1`. A full page means two **authorized** photos, not two rows examined.

## Check the answer with Cedar

```sh
uv add cedarpy
```

Save these files in the same directory. In `photos.cedarschema`, the owner's type is `User`, so the policy can compare the owner directly with the caller.

`photos.cedarschema`

```cedarschema
entity User;
entity Photo = { owner: User, visibility: String };
action "view" appliesTo { principal: [User], resource: [Photo] };
```

`view.cedar`

```cedar
permit(principal is User, action == Action::"view", resource is Photo)
when { resource.owner == principal || resource.visibility == "public" };
```

The request changes for each photo, but the caller, action and policy stay the same.

`gallery.py`

```python
from pathlib import Path

import cedarpy

here = Path(__file__).parent
policy = cedarpy.PolicySet.from_str((here / "view.cedar").read_text(encoding="utf-8"))
schema = cedarpy.Schema.from_str((here / "photos.cedarschema").read_text(encoding="utf-8"))


def alice_can_view(photo_id, owner, visibility):
    photo = {"type": "Photo", "id": photo_id}
    request = {
        "principal": {"type": "User", "id": "alice"},
        "action": {"type": "Action", "id": "view"},
        "resource": photo,
        "context": {},
    }
    attrs = {
        "owner": {"__entity": {"type": "User", "id": owner}},
        "visibility": visibility,
    }
    entities = [{"uid": photo, "attrs": attrs, "parents": []}]
    result = cedarpy.is_authorized(request, policy, entities, schema=schema)
    if result.diagnostics.errors:
        raise ValueError(result.diagnostics.errors)
    return result.allowed


photos = [
    ("1", "alice", "private"), ("2", "bob", "private"),
    ("3", "bob", "public"), ("4", "bob", "private"),
    ("5", "alice", "private"),
]
visible = [photo[0] for photo in photos if alice_can_view(*photo)]
print(visible[:2], visible[2:])
```

Run `uv run gallery.py` from that directory. Alice sees these pages:

```text
['1', '3'] ['5']
```

Change photo `3` from `public` to `private` and run the program again. The result is `['1', '5'] []`. A later read must use the new visibility, even if Alice still has the old URL or cursor.

## Where to enforce it

The loop above is a small reference answer, not a suggestion to load every row for every request. The [SQLAlchemy guide](../sqlalchemy/) shows how `get()` and `page()` can share a policy while SQL narrows the candidates. A Flask route or a background job can use that reader after authenticating the caller. Neither needs a second copy of the visibility rule.

Starting a bulk export is a different question. If that operation requires step-up, check permission to start it **and** check which photos the caller may export. The [web example](../fastapi/) shows the operation check.

This gallery is a flat version of Cedar's [PhotoFlash scenario](https://docs.cedarpolicy.com/overview/scenario.html). PhotoFlash also models group sharing and nested albums; neither is part of this example.
