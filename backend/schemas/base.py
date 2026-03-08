"""Base model with camelCase alias generation for JSON serialization."""

from pydantic import BaseModel
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model qui sérialise les champs en camelCase dans les réponses JSON."""

    model_config = {
        "alias_generator": to_camel,
        "populate_by_name": True,
    }
