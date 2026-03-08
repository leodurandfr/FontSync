from abc import ABC, abstractmethod
from pathlib import Path

import aiofiles
import aiofiles.os

from backend.config import settings


class StorageBackend(ABC):
    """Interface abstraite pour le stockage des fichiers de fonts."""

    @abstractmethod
    async def store(self, file_hash: str, file_data: bytes, extension: str) -> str:
        """Stocke un fichier et retourne le chemin relatif de stockage."""
        ...

    @abstractmethod
    async def retrieve(self, file_hash: str, extension: str) -> bytes:
        """Récupère le contenu d'un fichier à partir de son hash."""
        ...

    @abstractmethod
    async def delete(self, file_hash: str, extension: str) -> bool:
        """Supprime un fichier. Retourne True si le fichier existait."""
        ...

    @abstractmethod
    async def exists(self, file_hash: str, extension: str) -> bool:
        """Vérifie si un fichier existe dans le storage."""
        ...


class FilesystemStorage(StorageBackend):
    """Stockage sur le filesystem local, organisé par préfixe de hash."""

    def __init__(self, base_path: str | None = None) -> None:
        self.base_path = Path(base_path or settings.font_storage_path)

    def _build_path(self, file_hash: str, extension: str) -> Path:
        """Construit le chemin : base/ab/abcdef1234...ext"""
        prefix = file_hash[:2]
        filename = f"{file_hash}.{extension.lstrip('.')}"
        return self.base_path / prefix / filename

    async def store(self, file_hash: str, file_data: bytes, extension: str) -> str:
        """Stocke un fichier sur le filesystem."""
        path = self._build_path(file_hash, extension)
        await aiofiles.os.makedirs(path.parent, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(file_data)
        return str(path.relative_to(self.base_path))

    async def retrieve(self, file_hash: str, extension: str) -> bytes:
        """Récupère le contenu d'un fichier depuis le filesystem."""
        path = self._build_path(file_hash, extension)
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def delete(self, file_hash: str, extension: str) -> bool:
        """Supprime un fichier du filesystem."""
        path = self._build_path(file_hash, extension)
        if not path.exists():
            return False
        await aiofiles.os.remove(path)
        # Nettoie le répertoire préfixe s'il est vide
        try:
            path.parent.rmdir()
        except OSError:
            pass
        return True

    async def exists(self, file_hash: str, extension: str) -> bool:
        """Vérifie l'existence d'un fichier sur le filesystem."""
        path = self._build_path(file_hash, extension)
        return path.exists()


def get_storage_backend() -> StorageBackend:
    """Factory qui retourne le backend de stockage configuré."""
    if settings.storage_backend == "filesystem":
        return FilesystemStorage()
    raise ValueError(f"Backend de stockage inconnu : {settings.storage_backend}")
