"""Schémas Pydantic pour les familles de polices."""

from backend.schemas.base import CamelModel


class RegroupStats(CamelModel):
    """Statistiques retournées par le regroupement des fonts en familles."""

    families_created: int
    fonts_grouped: int
    fonts_skipped: int
