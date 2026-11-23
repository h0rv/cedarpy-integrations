from enum import StrEnum


class DocumentState(StrEnum):
    DRAFT = "draft"
    PUBLIC = "public"
    SEALED = "sealed"
