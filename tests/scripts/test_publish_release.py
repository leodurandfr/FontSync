"""Publication de l'app macOS : appcast contrôlé avant envoi (P1-6g, B-88, B-100).

`SUFeedURL` pointait vers `releases/latest/download/appcast.xml` et chaque
enclosure vers `releases/latest/download/FontSync-X.dmg` : la moindre release
« latest » sans appcast coupait les mises à jour de tous les clients, et chaque
ancienne version devenait introuvable dès qu'une nouvelle passait « latest ».
`publish-release.sh` téléversait en outre l'appcast local sans le lire.

Désormais : enclosures versionnées (`/releases/download/vX.Y.Z/`), flux stable
(asset `appcast.xml` de la release fixe `appcast`, jamais « latest »), et
`publish-release.sh` refuse d'envoyer quoi que ce soit si l'appcast ne décrit
pas exactement le DMG publié. Un faux `gh` journalise ses appels.
"""

from __future__ import annotations

import json
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PUBLISH = REPO / "scripts" / "publish-release.sh"
RELEASE = REPO / "scripts" / "release-macos-app.sh"
CHECK = REPO / "scripts" / "lib" / "check-appcast.py"
INFO_PLIST = REPO / "macos-app" / "Info.plist"

SLUG = "leodurandfr/FontSync"
STABLE_FEED = f"https://github.com/{SLUG}/releases/download/appcast/appcast.xml"
VERSION = "0.1.2"
BUILD = "6"
SIG = "c2lnbmF0dXJlLWZhY3RpY2UtcG91ci1sZS10ZXN0LTAxMjM0NTY3ODk="

FAKE_GH = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["GH_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:2] == ["release", "view"]:
    missing = os.environ.get("GH_MISSING", "").split()
    sys.exit(1 if args[2] in missing else 0)
if " ".join(args[:3]) == os.environ.get("GH_FAIL"):
    sys.exit(1)
sys.exit(0)
"""

FAKE_SIGN = """#!/bin/sh
printf 'sparkle:edSignature="%s" length="%s"\\n' "$FAKE_SIG" "$(wc -c < "$1" | tr -d ' ')"
"""


def url(version: str, name: str | None = None) -> str:
    return f"https://github.com/{SLUG}/releases/download/v{version}/{name or f'FontSync-{version}.dmg'}"


def item(
    short: str,
    *,
    build: str = BUILD,
    enclosure: str | None = None,
    length: int | None = None,
    signature: str | None = SIG,
) -> str:
    sig = f' sparkle:edSignature="{signature}"' if signature is not None else ""
    return f"""
        <item>
            <title>{short}</title>
            <sparkle:version>{build}</sparkle:version>
            <sparkle:shortVersionString>{short}</sparkle:shortVersionString>
            <sparkle:minimumSystemVersion>14.0</sparkle:minimumSystemVersion>
            <sparkle:hardwareRequirements>arm64</sparkle:hardwareRequirements>
            <enclosure url="{enclosure or url(short)}" length="{length if length is not None else 1}" type="application/octet-stream"{sig}/>
        </item>"""


def appcast(*items: str) -> str:
    return (
        '<?xml version="1.0" standalone="yes"?>\n'
        '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">\n'
        "    <channel>\n        <title>FontSync</title>"
        + "".join(items)
        + "\n    </channel>\n</rss>\n"
    )


class Env:
    """Copie minimale du dépôt (script + scripts/lib) et `macos-app/dist` jetable."""

    def __init__(self, tmp: Path) -> None:
        repo = tmp / "repo"
        (repo / "scripts").mkdir(parents=True)
        shutil.copy2(PUBLISH, repo / "scripts" / PUBLISH.name)
        if (REPO / "scripts" / "lib").is_dir():
            shutil.copytree(REPO / "scripts" / "lib", repo / "scripts" / "lib")
        self.script = repo / "scripts" / PUBLISH.name
        self.repo = repo
        self.git("init", "-q")
        self.git("commit", "-q", "--allow-empty", "-m", "init")
        self.tag("v0.1.1", f"v{VERSION}")
        self.dist = repo / "macos-app" / "dist"
        self.dist.mkdir(parents=True)
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.log = tmp / "gh.log"
        self.log.touch()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        (self.bin / "python3").symlink_to(sys.executable)
        self.sign = tmp / "sign_update"
        self.sign.write_text(FAKE_SIGN)
        self.sign.chmod(0o755)
        self.dmg = self.dist / f"FontSync-{VERSION}.dmg"
        self.dmg.write_bytes(b"dmg-factice" * 100)
        self.size = self.dmg.stat().st_size

    def git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(self.repo),
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "test",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "test",
            },
        )

    def tag(self, *names: str) -> None:
        for name in names:
            self.git("tag", name)

    def write_appcast(self, text: str) -> None:
        (self.dist / "appcast.xml").write_text(text)

    def good(self, *extra: str, **kw: object) -> str:
        kw.setdefault("length", self.size)
        return appcast(item(VERSION, **kw), *extra)  # type: ignore[arg-type]

    def run(self, **env: str) -> subprocess.CompletedProcess[str]:
        full = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.dist.parent),
            "TMPDIR": str(self.dist.parent),
            "GH_LOG": str(self.log),
            "SKIP_BUILD": "1",
            "VERSION": VERSION,
            "BUILD": BUILD,
            "SIGN_UPDATE": "none",
            "FAKE_SIG": SIG,
        }
        full.update(env)
        return subprocess.run(
            ["bash", str(self.script)],
            check=False,
            env=full,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def writes(self) -> list[list[str]]:
        """Appels gh qui modifient GitHub (tout sauf `release view`)."""
        return [c for c in self.calls() if c[:2] != ["release", "view"]]


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def assert_refused(env: Env, proc: subprocess.CompletedProcess[str], why: str) -> None:
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert env.writes() == [], env.calls()
    assert re.search(why, proc.stdout + proc.stderr, re.IGNORECASE), (
        proc.stdout + proc.stderr
    )


# --- Refus avant tout envoi -------------------------------------------------


def test_appcast_without_this_version_is_refused(env: Env) -> None:
    env.write_appcast(appcast(item("0.1.1", length=env.size)))
    assert_refused(env, env.run(), r"0\.1\.2")


def test_missing_appcast_refused_when_publishing(env: Env) -> None:
    assert_refused(env, env.run(PUBLISH="1"), r"appcast")


def test_enclosure_through_latest_is_refused(env: Env) -> None:
    env.write_appcast(
        env.good(
            enclosure=f"https://github.com/{SLUG}/releases/latest/download/FontSync-{VERSION}.dmg"
        )
    )
    assert_refused(env, env.run(), r"enclosure|url")


def test_enclosure_of_another_file_is_refused(env: Env) -> None:
    env.write_appcast(env.good(enclosure=url(VERSION, "FontSync-0.1.1.dmg")))
    assert_refused(env, env.run(), r"enclosure|url")


def test_length_mismatch_is_refused(env: Env) -> None:
    env.write_appcast(env.good(length=env.size + 1))
    assert_refused(env, env.run(), r"length|taille")


def test_build_mismatch_is_refused(env: Env) -> None:
    env.write_appcast(env.good(build="5"))
    assert_refused(env, env.run(), r"build|sparkle:version")


def test_unsigned_item_is_refused(env: Env) -> None:
    env.write_appcast(env.good(signature=None))
    assert_refused(env, env.run(), r"edSignature|signature")


def test_duplicate_items_for_version_are_refused(env: Env) -> None:
    env.write_appcast(
        appcast(item(VERSION, length=env.size), item(VERSION, length=env.size))
    )
    assert_refused(env, env.run(), r"0\.1\.2")


def test_older_item_through_latest_is_refused(env: Env) -> None:
    """Un ancien item hérité d'un appcast `latest/` deviendrait introuvable (B-100)."""
    older = item(
        "0.1.1",
        build="5",
        enclosure=f"https://github.com/{SLUG}/releases/latest/download/FontSync-0.1.1.dmg",
    )
    env.write_appcast(env.good(older))
    assert_refused(env, env.run(), r"0\.1\.1")


def test_signature_mismatch_with_sign_update_is_refused(env: Env) -> None:
    env.write_appcast(env.good())
    proc = env.run(SIGN_UPDATE=str(env.sign), FAKE_SIG="YXV0cmUtc2lnbmF0dXJl")
    assert_refused(env, proc, r"edSignature|signature")


def test_missing_dmg_is_refused(env: Env) -> None:
    env.write_appcast(env.good())
    env.dmg.unlink()
    assert_refused(env, env.run(), r"introuvable|dmg")


# --- Envois attendus ----------------------------------------------------------


def test_consistent_appcast_publishes_versioned_then_stable_feed(env: Env) -> None:
    env.write_appcast(
        env.good(item("0.1.1", build="5", length=7, enclosure=url("0.1.1")))
    )
    proc = env.run(PUBLISH="1", SIGN_UPDATE=str(env.sign), GH_MISSING="appcast")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    writes = env.writes()
    appcast_path = str(env.dist / "appcast.xml")
    upload = next(c for c in writes if c[:3] == ["release", "upload", f"v{VERSION}"])
    assert str(env.dmg) in upload and appcast_path in upload and "--clobber" in upload
    publish = next(c for c in writes if c[:3] == ["release", "edit", f"v{VERSION}"])
    assert "--draft=false" in publish
    # Les clients 0.1.1 lisent encore releases/latest/download/appcast.xml.
    assert "--latest" in publish
    create = next(c for c in writes if c[:3] == ["release", "create", "appcast"])
    assert "--latest=false" in create and "--draft" not in create
    assert "--prerelease" in create
    stable = next(c for c in writes if c[:3] == ["release", "upload", "appcast"])
    assert stable[3:] == [appcast_path, "--clobber"] or set(stable[3:]) >= {
        appcast_path,
        "--clobber",
    }
    # Le flux stable n'est mis à jour qu'une fois la release versionnée publiée
    # (sinon son enclosure renverrait 404).
    assert writes.index(upload) < writes.index(publish) < writes.index(stable)


def test_existing_stable_release_is_not_recreated(env: Env) -> None:
    env.write_appcast(env.good())
    proc = env.run(PUBLISH="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not any(c[:3] == ["release", "create", "appcast"] for c in env.writes())
    assert any(c[:3] == ["release", "upload", "appcast"] for c in env.writes())


def test_draft_upload_leaves_stable_feed_alone(env: Env) -> None:
    env.write_appcast(env.good())
    proc = env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    writes = env.writes()
    assert any(c[:3] == ["release", "upload", f"v{VERSION}"] for c in writes)
    assert not any("appcast" in c[2:3] for c in writes), writes
    assert not any(c[:2] == ["release", "edit"] for c in writes), writes


def test_draft_upload_without_appcast_sends_only_the_dmg(env: Env) -> None:
    proc = env.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (upload,) = [c for c in env.writes() if c[:2] == ["release", "upload"]]
    assert upload[2] == f"v{VERSION}" and str(env.dmg) in upload
    assert not any(a.endswith("appcast.xml") for a in upload)


# --- Configuration figée --------------------------------------------------------


def test_info_plist_feed_is_the_stable_url() -> None:
    plist = plistlib.loads(INFO_PLIST.read_bytes())
    assert plist["SUFeedURL"] == STABLE_FEED


def code_lines(path: Path) -> list[str]:
    return [
        ln for ln in path.read_text().splitlines() if not ln.lstrip().startswith("#")
    ]


@pytest.mark.parametrize("script", [PUBLISH, RELEASE], ids=lambda p: p.name)
def test_scripts_never_use_latest_download(script: Path) -> None:
    """Seuls les commentaires citent encore l'ancien flux (clients ≤ 0.1.1)."""
    assert not [ln for ln in code_lines(script) if "releases/latest" in ln]


# --- Relecture adversariale ---------------------------------------------------

UPLOAD = "release " + "upload"


def test_every_write_names_the_feed_repository(env: Env) -> None:
    """Sans --repo, gh viserait le dépôt du dossier courant (fork, autre remote)."""
    env.write_appcast(env.good())
    assert env.run(PUBLISH="1").returncode == 0
    for call in env.calls():
        assert call[call.index("--repo") + 1] == SLUG, call


def test_failing_sign_update_refuses_with_a_message(env: Env) -> None:
    env.write_appcast(env.good())
    broken = env.dist.parent / "broken-sign"
    broken.write_text("#!/bin/sh\necho boom >&2\nexit 3\n")
    broken.chmod(0o755)
    assert_refused(env, env.run(SIGN_UPDATE=str(broken)), r"sign_update")


def test_missing_sign_update_is_reported_not_fatal(env: Env) -> None:
    """Sans build local (SKIP_BUILD sur un arbre propre), pas de mort muette."""
    env.write_appcast(env.good())
    proc = env.run(SIGN_UPDATE="")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "sign_update introuvable" in proc.stdout


@pytest.mark.parametrize("version", ["0.2.0-rc1", "0.1.2-beta.1"])
def test_prerelease_is_never_published_to_the_stable_feed(
    env: Env, version: str
) -> None:
    env.tag(f"v{version}")
    env.dmg = env.dmg.rename(env.dist / f"FontSync-{version}.dmg")
    env.write_appcast(appcast(item(version, length=env.size)))
    assert_refused(env, env.run(PUBLISH="1", VERSION=version), r"pré-release")


def test_older_version_is_not_published_over_a_newer_one(env: Env) -> None:
    env.tag("v0.1.3")
    env.write_appcast(env.good())
    assert_refused(env, env.run(PUBLISH="1"), r"v0\.1\.3")


def test_publish_requires_the_local_tag(env: Env) -> None:
    env.git("tag", "-d", f"v{VERSION}")
    env.write_appcast(env.good())
    assert_refused(env, env.run(PUBLISH="1"), r"tag")


def test_failed_stable_upload_says_how_to_retry(env: Env) -> None:
    env.write_appcast(env.good())
    proc = env.run(PUBLISH="1", GH_FAIL=f"{UPLOAD} appcast")
    assert proc.returncode != 0
    assert f"gh {UPLOAD} appcast" in proc.stderr


def test_other_item_with_higher_build_is_refused(env: Env) -> None:
    older = item("0.1.1", build="99", length=7, enclosure=url("0.1.1"))
    env.write_appcast(env.good(older))
    assert_refused(env, env.run(), r"build")


def test_item_outside_channel_is_refused(env: Env) -> None:
    text = env.good().replace("<channel>", "<channel></channel><other>")
    text = text.replace("</channel>\n</rss>", "</other>\n</rss>")
    env.write_appcast(text)
    assert_refused(env, env.run(), r"found 0")


def test_delta_enclosure_elsewhere_is_refused(env: Env) -> None:
    delta = (
        '<sparkle:deltas><enclosure url="https://example.com/evil.delta" '
        'sparkle:deltaFrom="5" length="1" type="application/octet-stream"/>'
        "</sparkle:deltas>"
    )
    env.write_appcast(env.good().replace("</item>", delta + "</item>", 1))
    assert_refused(env, env.run(), r"evil\.delta")
