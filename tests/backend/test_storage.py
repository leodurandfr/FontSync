import hashlib

import pytest

from backend.services.storage import FilesystemStorage


@pytest.fixture
def storage(tmp_path: str) -> FilesystemStorage:
    return FilesystemStorage(base_path=str(tmp_path))


@pytest.fixture
def sample_font() -> tuple[str, bytes, str]:
    """Retourne (hash, data, extension) pour un fichier de test."""
    data = b"fake font data for testing"
    file_hash = hashlib.sha256(data).hexdigest()
    return file_hash, data, "ttf"


@pytest.mark.asyncio
async def test_store_creates_file(
    storage: FilesystemStorage, sample_font: tuple[str, bytes, str]
) -> None:
    file_hash, data, ext = sample_font
    path = await storage.store(file_hash, data, ext)

    assert path == f"{file_hash[:2]}/{file_hash}.{ext}"
    assert await storage.exists(file_hash, ext)


@pytest.mark.asyncio
async def test_retrieve_returns_stored_data(
    storage: FilesystemStorage, sample_font: tuple[str, bytes, str]
) -> None:
    file_hash, data, ext = sample_font
    await storage.store(file_hash, data, ext)

    result = await storage.retrieve(file_hash, ext)
    assert result == data


@pytest.mark.asyncio
async def test_delete_removes_file(
    storage: FilesystemStorage, sample_font: tuple[str, bytes, str]
) -> None:
    file_hash, data, ext = sample_font
    await storage.store(file_hash, data, ext)

    assert await storage.delete(file_hash, ext) is True
    assert await storage.exists(file_hash, ext) is False


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(
    storage: FilesystemStorage,
) -> None:
    assert await storage.delete("nonexistent", "ttf") is False


@pytest.mark.asyncio
async def test_exists_false_when_not_stored(
    storage: FilesystemStorage,
) -> None:
    assert await storage.exists("nonexistent", "ttf") is False


@pytest.mark.asyncio
async def test_store_with_dotted_extension(
    storage: FilesystemStorage,
) -> None:
    """L'extension avec ou sans point doit donner le même résultat."""
    data = b"test"
    file_hash = hashlib.sha256(data).hexdigest()

    path = await storage.store(file_hash, data, ".otf")
    assert path.endswith(f"{file_hash}.otf")


@pytest.mark.asyncio
async def test_store_overwrites_existing(
    storage: FilesystemStorage, sample_font: tuple[str, bytes, str]
) -> None:
    file_hash, data, ext = sample_font
    await storage.store(file_hash, data, ext)

    new_data = b"updated font data"
    await storage.store(file_hash, new_data, ext)

    result = await storage.retrieve(file_hash, ext)
    assert result == new_data


@pytest.mark.asyncio
async def test_retrieve_nonexistent_raises(
    storage: FilesystemStorage,
) -> None:
    with pytest.raises(FileNotFoundError):
        await storage.retrieve("nonexistent", "ttf")


@pytest.mark.asyncio
async def test_delete_cleans_empty_prefix_dir(
    storage: FilesystemStorage, sample_font: tuple[str, bytes, str], tmp_path: str
) -> None:
    """Le répertoire préfixe est supprimé s'il devient vide après delete."""
    file_hash, data, ext = sample_font
    await storage.store(file_hash, data, ext)

    prefix_dir = storage.base_path / file_hash[:2]
    assert prefix_dir.is_dir()

    await storage.delete(file_hash, ext)
    assert not prefix_dir.exists()


@pytest.mark.asyncio
async def test_store_with_real_font(storage: FilesystemStorage) -> None:
    """Test avec un vrai fichier TTF depuis les fixtures."""
    import pathlib

    fixture = (
        pathlib.Path(__file__).parent.parent / "fixtures" / "TTHovesPro-Rg.ttf"
    )
    if not fixture.exists():
        pytest.skip("Fixture TTF non disponible")

    data = fixture.read_bytes()
    file_hash = hashlib.sha256(data).hexdigest()

    path = await storage.store(file_hash, data, "ttf")
    assert await storage.exists(file_hash, "ttf")

    retrieved = await storage.retrieve(file_hash, "ttf")
    assert retrieved == data
    assert len(retrieved) == len(data)
