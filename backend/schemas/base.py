"""Base model with camelCase alias generation for JSON serialization."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, SerializerFunctionWrapHandler, field_serializer
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model qui sérialise les champs en camelCase dans les réponses JSON."""

    model_config = {
        "alias_generator": to_camel,
        "populate_by_name": True,
    }

    @field_serializer("*", mode="wrap")
    def _serialize_utc_aware(
        self, value: Any, handler: SerializerFunctionWrapHandler
    ) -> Any:
        """Émet tout datetime naïf comme de l'UTC explicite (suffixe `Z`).

        SQLite ne stocke pas de fuseau : malgré `DateTime(timezone=True)`, les
        colonnes reviennent en datetime **naïfs**, que Pydantic sérialisait tels
        quels (`2026-08-10T13:45:04.141453`). Or `new Date(...)` interprète une
        date sans offset comme de l'**heure locale** : le frontend décalait donc
        chaque horodatage du fuseau du navigateur (« vu il y a 2 h » pour un
        appareil vu il y a 7 minutes, en UTC+2).

        Toutes les dates écrites en base le sont en UTC (`datetime.now(utc)`) :
        un datetime naïf qui sort d'ici est donc de l'UTC, et on le déclare.
        Les valeurs déjà situées et les champs non-datetime passent inchangés
        au sérialiseur par défaut.
        """
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return handler(value)
