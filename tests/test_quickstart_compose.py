"""Le démarrage rapide documenté produit un .env que le compose NAS accepte (P1-8c, M-13).

`docker-compose.nas.yml` exige `WATCHTOWER_TOKEN` (`${WATCHTOWER_TOKEN:?…}`) ;
le README, l'en-tête du compose et le pas-à-pas Synology doivent l'écrire, sans
quoi `docker compose up` refuse de démarrer en suivant la doc. Aucun autre
secret n'est demandé : l'accès se fait par compte.
On exécute la ligne du README dans un dossier jetable, puis `docker compose
config` sur une copie du compose (ignoré sans CLI docker).
"""

from __future__ import annotations

import os
import pwd
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
COMPOSE = REPO / "docker-compose.nas.yml"
INSTALL = REPO / "docs" / "INSTALL-NAS.md"


SHELL_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


def env_lines(text: str) -> list[str]:
    """Commandes qui écrivent le .env (sans le `#` d'un commentaire de compose)."""
    return [
        ln.strip().lstrip("#").strip()
        for ln in text.splitlines()
        if "> .env" in ln and "printf" in ln
    ]


def readme_env_commands() -> list[str]:
    """Lignes du démarrage rapide du README qui écrivent le .env."""
    text = README.read_text()
    start = text.index("### 1. Start the server")
    block = text[start : text.index("```", text.index("```bash", start) + 7)]
    lines = [ln for ln in block.splitlines() if "> .env" in ln or ">> .env" in ln]
    assert lines, "le démarrage rapide du README n'écrit plus de .env"
    return lines


def docker_env(home: Path) -> dict[str, str]:
    """HOME jetable (le conftest protège le vrai), mais DOCKER_CONFIG réel en
    lecture : c'est là que Docker Desktop/OrbStack posent le plugin compose."""
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home)}
    real = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".docker"
    if real.is_dir():
        env["DOCKER_CONFIG"] = str(real)
    return env


def docker_compose(home: Path) -> list[str] | None:
    docker = shutil.which("docker") or (
        "/usr/local/bin/docker" if Path("/usr/local/bin/docker").exists() else None
    )
    if docker is None:
        return None
    probe = subprocess.run(
        [docker, "compose", "version"],
        capture_output=True,
        text=True,
        check=False,
        env=docker_env(home),
    )
    return [docker, "compose"] if probe.returncode == 0 else None


def test_readme_quickstart_env_satisfies_the_nas_compose(tmp_path: Path) -> None:
    compose = docker_compose(tmp_path)
    if compose is None:
        pytest.skip("CLI docker compose absente")
    if shutil.which("openssl", path=SHELL_PATH) is None:
        pytest.skip("openssl absent")
    shutil.copy(COMPOSE, tmp_path / COMPOSE.name)
    for line in readme_env_commands():
        subprocess.run(
            ["bash", "-c", line], cwd=tmp_path, check=True, env={"PATH": SHELL_PATH}
        )
    written = (tmp_path / ".env").read_text().splitlines()
    # Seul secret : celui du bouton « Mettre à jour ». L'accès se fait par
    # compte, créé au premier accès.
    assert [ln.split("=", 1)[0] for ln in written] == ["WATCHTOWER_TOKEN"]
    tokens = [ln.split("=", 1)[1] for ln in written]
    assert all(len(t) >= 32 for t in tokens)
    result = subprocess.run(
        [*compose, "-f", COMPOSE.name, "config", "--quiet"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=docker_env(tmp_path),
    )
    assert result.returncode == 0, result.stderr

    # La doc affirme que le compose refuse de démarrer sans ce secret.
    (tmp_path / ".env").write_text("")
    missing = subprocess.run(
        [*compose, "-f", COMPOSE.name, "config", "--quiet"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=docker_env(tmp_path),
    )
    assert missing.returncode != 0
    assert "WATCHTOWER_TOKEN" in missing.stderr


def test_every_quickstart_generates_the_update_secret() -> None:
    """README (deux endroits), en-tête du compose et INSTALL-NAS : le secret
    du bouton de mise à jour, et la même commande qui l'écrit."""
    readme = README.read_text()
    for section in ("### 1. Start the server", "single-container"):
        idx = readme.lower().index(section.lower())
        snippet = readme[idx : readme.index("```", readme.index("```bash", idx) + 7)]
        assert "WATCHTOWER_TOKEN" in snippet, section
    header = "\n".join(
        ln for ln in COMPOSE.read_text().splitlines()[:25] if ln.startswith("#")
    )
    assert "WATCHTOWER_TOKEN" in header
    install = INSTALL.read_text()
    synology = install[install.index("### On Synology Container Manager") :]
    synology = synology[: synology.index("\n---")]
    assert "WATCHTOWER_TOKEN" in synology
    assert re.search(r"`db`, `fonts` and `backups`", synology)


def test_all_quickstarts_use_the_same_env_command() -> None:
    """README (deux blocs), en-tête du compose, INSTALL-NAS : la même commande
    exacte, qui écrit le secret — la ligne du README est exécutée et
    vérifiée ci-dessus, les autres ne peuvent pas diverger."""
    readme = env_lines(README.read_text())
    header = env_lines(
        "\n".join(
            ln for ln in COMPOSE.read_text().splitlines()[:25] if ln.startswith("#")
        )
    )
    install = env_lines(INSTALL.read_text())
    assert len(readme) == 2 and len(header) == 1 and len(install) >= 1
    reference = readme_env_commands()[0].strip()
    assert "WATCHTOWER_TOKEN=%s" in reference
    assert set(readme + header + install) == {reference}


@pytest.mark.parametrize("shell", ["bash", "sh", "zsh"])
def test_quickstart_never_overwrites_an_existing_env(
    tmp_path: Path, shell: str
) -> None:
    """Relancer la commande sur une installation existante écraserait son
    .env (et le secret de mise à jour qu'il porte) : elle doit refuser."""
    if shutil.which(shell, path=SHELL_PATH) is None:
        pytest.skip(f"{shell} absent")
    if shutil.which("openssl", path=SHELL_PATH) is None:
        pytest.skip("openssl absent")
    env_file = tmp_path / ".env"
    env_file.write_text("WATCHTOWER_TOKEN=keep-me\n")
    for line in readme_env_commands():
        result = subprocess.run(
            [shell, "-c", line],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": SHELL_PATH},
        )
        assert result.returncode != 0
    assert env_file.read_text() == "WATCHTOWER_TOKEN=keep-me\n"
