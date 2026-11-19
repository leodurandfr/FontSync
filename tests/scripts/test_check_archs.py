"""Contrôles d'architecture de la release macOS (P1-6f, M-21).

L'app 0.1.1 était universelle (x86_64 + arm64) alors que son agent embarqué
n'était qu'arm64 : sur un Mac Intel, l'app se lançait avec un agent incapable de
tourner. `scripts/lib/check-archs.sh` bloque la release au moindre écart, et
`scripts/lib/check-appcast-arch.py` vérifie que l'appcast le déclare à Sparkle.

Les binaires sont des en-têtes Mach-O écrits à la main : `lipo -archs` n'a
besoin que d'eux. Chaque cas tourne avec un faux `lipo` portable (la CI est sous
Linux) et, sous macOS, avec le vrai.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK_ARCHS = REPO / "scripts" / "lib" / "check-archs.sh"
CHECK_APPCAST = REPO / "scripts" / "lib" / "check-appcast-arch.py"
RELEASE = REPO / "scripts" / "release-macos-app.sh"

CPU = {"x86_64": 0x01000007, "arm64": 0x0100000C}
# CPU_SUBTYPE_X86_64_ALL = 3, CPU_SUBTYPE_ARM64_ALL = 0 : le vrai lipo lit
# « unknown » sur une tranche x86_64 de sous-type 0.
SUBTYPE = {"x86_64": 3, "arm64": 0}
NAMES = {v: k for k, v in CPU.items()}


def thin(arch: str) -> bytes:
    """En-tête mach_header_64 minimal (exécutable, sans commande de chargement)."""
    return struct.pack("<IiiIIIII", 0xFEEDFACF, CPU[arch], SUBTYPE[arch], 2, 0, 0, 0, 0)


def fat(*archs: str) -> bytes:
    """Binaire universel : en-tête fat (big-endian) puis une tranche par arche."""
    align = 12
    header = struct.pack(">II", 0xCAFEBABE, len(archs))
    entries, slices = b"", b""
    offset = 1 << align
    for arch in archs:
        body = thin(arch)
        entries += struct.pack(
            ">iiIII", CPU[arch], SUBTYPE[arch], offset, len(body), align
        )
        slices += body.ljust(1 << align, b"\0")
        offset += 1 << align
    return (header + entries).ljust(1 << align, b"\0") + slices


def binary(*archs: str) -> bytes:
    return thin(archs[0]) if len(archs) == 1 else fat(*archs)


FAKE_LIPO = f"""#!{sys.executable}
# Faux `lipo -archs` : lit l'en-tête Mach-O (mince ou fat) d'un fichier.
import struct, sys
NAMES = {NAMES!r}
if len(sys.argv) != 3 or sys.argv[1] != "-archs":
    sys.exit(2)
data = open(sys.argv[2], "rb").read()
if data[:4] == bytes.fromhex("cafebabe"):
    n = struct.unpack(">I", data[4:8])[0]
    cpus = [struct.unpack(">i", data[8 + 20 * i : 12 + 20 * i])[0] for i in range(n)]
elif data[:4] == bytes.fromhex("cffaedfe"):
    cpus = [struct.unpack("<i", data[4:8])[0]]
else:
    sys.stderr.write("not a Mach-O file\\n")
    sys.exit(1)
print(" ".join(NAMES.get(c, "unknown") for c in cpus))
"""


@pytest.fixture(params=["fake", "real"])
def lipo(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    if request.param == "real":
        real = shutil.which("lipo")
        if sys.platform != "darwin" or real is None:
            pytest.skip("lipo réel : macOS uniquement")
        probe = tmp_path / "probe"
        probe.write_bytes(thin("arm64"))
        if subprocess.run(
            [real, "-archs", str(probe)], capture_output=True, check=False
        ).returncode:
            pytest.skip("lipo présent mais inutilisable (outils Xcode absents)")
        return real
    fake = tmp_path / "fake-lipo"
    fake.write_text(FAKE_LIPO)
    fake.chmod(0o755)
    return str(fake)


def make_app(
    root: Path,
    *,
    main: tuple[str, ...] = ("arm64",),
    python: tuple[str, ...] | None = ("arm64",),
    libs: dict[str, tuple[str, ...] | bytes] | None = None,
) -> Path:
    """Arborescence FontSync.app factice, calquée sur la release réelle."""
    app = root / "FontSync.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "FontSync").write_bytes(binary(*main))
    venv = app / "Contents" / "Resources" / "agent-venv"
    (venv / "bin").mkdir(parents=True)
    if python is not None:
        (venv / "bin" / "python3.12").write_bytes(binary(*python))
        (venv / "bin" / "python3").symlink_to("python3.12")
    (venv / "bin" / "pip").write_text("#!/bin/sh\n")
    site = venv / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    default_libs: dict[str, tuple[str, ...] | bytes] = {
        # Roues universal2 (pyobjc, fonttools) : tranche x86_64 inoffensive.
        "objc/_objc.cpython-312-darwin.so": ("x86_64", "arm64"),
        "yaml/_yaml.cpython-312-darwin.so": ("arm64",),
        "../../libpython3.12.dylib": ("arm64",),
    }
    for rel, content in (libs if libs is not None else default_libs).items():
        path = (site / rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else binary(*content))
    return app


def run_check(app: Path, expect: str, lipo: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CHECK_ARCHS), "--expect", expect, str(app)],
        capture_output=True,
        check=False,
        text=True,
        env={"PATH": "/usr/bin:/bin", "LIPO": lipo},
    )


# --- check-archs.sh -----------------------------------------------------------


def test_arm64_release_passes(tmp_path: Path, lipo: str) -> None:
    app = make_app(tmp_path)
    result = run_check(app, "arm64", lipo)
    assert result.returncode == 0, result.stdout + result.stderr
    # app + interpréteur + 3 bibliothèques natives
    assert "5 binaires" in result.stdout


def test_universal_app_with_arm64_agent_is_refused(tmp_path: Path, lipo: str) -> None:
    """La 0.1.1 telle que publiée : app universelle, agent arm64 seul."""
    app = make_app(tmp_path, main=("x86_64", "arm64"))
    result = run_check(app, "arm64", lipo)
    assert result.returncode == 1
    assert "Contents/MacOS/FontSync" in result.stdout


def test_x86_64_extension_is_refused(tmp_path: Path, lipo: str) -> None:
    app = make_app(
        tmp_path,
        libs={
            "objc/_objc.cpython-312-darwin.so": ("x86_64", "arm64"),
            "fontTools/cu2qu/cu2qu.cpython-312-darwin.so": ("x86_64",),
        },
    )
    result = run_check(app, "arm64", lipo)
    assert result.returncode == 1
    assert "cu2qu.cpython-312-darwin.so" in result.stdout
    assert "_objc" not in result.stdout


def test_x86_64_interpreter_is_refused(tmp_path: Path, lipo: str) -> None:
    app = make_app(tmp_path, python=("x86_64",))
    result = run_check(app, "arm64", lipo)
    assert result.returncode == 1
    assert "python3.12" in result.stdout


def test_missing_interpreter_is_refused(tmp_path: Path, lipo: str) -> None:
    app = make_app(tmp_path, python=None)
    result = run_check(app, "arm64", lipo)
    assert result.returncode == 1
    assert "python3.12" in result.stdout


def test_missing_main_binary_is_refused(tmp_path: Path, lipo: str) -> None:
    app = make_app(tmp_path)
    (app / "Contents" / "MacOS" / "FontSync").unlink()
    result = run_check(app, "arm64", lipo)
    assert result.returncode == 1
    assert "Contents/MacOS/FontSync" in result.stdout


def test_unreadable_library_is_refused(tmp_path: Path, lipo: str) -> None:
    app = make_app(tmp_path, libs={"broken/_x.cpython-312-darwin.so": b"not mach-o"})
    result = run_check(app, "arm64", lipo)
    assert result.returncode == 1
    assert "_x.cpython-312-darwin.so" in result.stdout


def add_sparkle(app: Path, archs: dict[str, tuple[str, ...]] | None = None) -> None:
    """Sparkle.framework calqué sur la 0.1.1 : exécutables sans extension, liens."""
    fw = app / "Contents" / "Frameworks" / "Sparkle.framework"
    vb = fw / "Versions" / "B"
    bins = {
        "Sparkle": ("x86_64", "arm64"),
        "Autoupdate": ("x86_64", "arm64"),
        "Updater.app/Contents/MacOS/Updater": ("x86_64", "arm64"),
        "XPCServices/Downloader.xpc/Contents/MacOS/Downloader": ("x86_64", "arm64"),
        "XPCServices/Installer.xpc/Contents/MacOS/Installer": ("x86_64", "arm64"),
    }
    bins.update(archs or {})
    for rel, arch in bins.items():
        path = vb / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(binary(*arch))
        path.chmod(0o755)
    (vb / "Resources").mkdir()
    (vb / "Resources" / "Info.plist").write_text("<plist/>")
    (fw / "Versions" / "Current").symlink_to("B")
    for name in ("Sparkle", "Autoupdate", "Updater.app", "XPCServices", "Resources"):
        (fw / name).symlink_to(f"Versions/Current/{name}")


def test_sparkle_executables_are_checked(tmp_path: Path, lipo: str) -> None:
    app = make_app(tmp_path)
    add_sparkle(app)
    result = run_check(app, "arm64", lipo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "10 binaires" in result.stdout


def test_x86_64_sparkle_helper_is_refused(tmp_path: Path, lipo: str) -> None:
    """Un Autoupdate sans tranche arm64 casserait les mises à jour sans bruit."""
    app = make_app(tmp_path)
    add_sparkle(app, {"Autoupdate": ("x86_64",)})
    result = run_check(app, "arm64", lipo)
    assert result.returncode == 1
    assert "Versions/B/Autoupdate" in result.stdout


def test_symlinked_library_is_checked(tmp_path: Path, lipo: str) -> None:
    app = make_app(tmp_path)
    site = app / "Contents" / "Resources" / "agent-venv" / "lib" / "python3.12"
    (site / "x86-only").write_bytes(binary("x86_64"))
    (site / "site-packages" / "_sym.cpython-312-darwin.so").symlink_to("../x86-only")
    result = run_check(app, "arm64", lipo)
    assert result.returncode == 1
    assert "_sym.cpython-312-darwin.so" in result.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root lit tout")
def test_unreadable_directory_stops_the_check(tmp_path: Path, lipo: str) -> None:
    """Un `find` en échec ne doit jamais aboutir à « OK » (bibliothèque cachée)."""
    app = make_app(tmp_path)
    hidden = app / "Contents" / "Resources" / "agent-venv" / "lib" / "locked"
    hidden.mkdir()
    (hidden / "_bad.cpython-312-darwin.so").write_bytes(binary("x86_64"))
    hidden.chmod(0)
    try:
        result = run_check(app, "arm64", lipo)
    finally:
        hidden.chmod(0o755)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Architectures OK" not in result.stdout


def test_failed_sort_stops_the_check(tmp_path: Path, lipo: str) -> None:
    """Une erreur dans la substitution de processus n'est pas remontée par bash."""
    app = make_app(tmp_path)
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "sort").write_text(
        '#!/bin/sh\nfor a in "$@"; do [ "$a" = -z ] && '
        "{ echo 'sort: invalid option -- z' >&2; exit 2; }; done\n"
        'exec /usr/bin/sort "$@"\n'
    )
    (shim / "sort").chmod(0o755)
    result = subprocess.run(
        ["bash", str(CHECK_ARCHS), "--expect", "arm64", str(app)],
        capture_output=True,
        check=False,
        text=True,
        env={"PATH": f"{shim}:/usr/bin:/bin", "LIPO": lipo},
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Architectures OK" not in result.stdout
    assert "incomplète" in result.stderr


def test_universal2_requires_both_slices_everywhere(tmp_path: Path, lipo: str) -> None:
    ok = make_app(
        tmp_path / "ok",
        main=("x86_64", "arm64"),
        python=("x86_64", "arm64"),
        libs={"objc/_objc.cpython-312-darwin.so": ("x86_64", "arm64")},
    )
    assert run_check(ok, "arm64 x86_64", lipo).returncode == 0

    # Même écart que la 0.1.1, vu depuis une release universal2.
    half = make_app(tmp_path / "half", main=("x86_64", "arm64"))
    result = run_check(half, "x86_64 arm64", lipo)
    assert result.returncode == 1
    assert "python3.12" in result.stdout


def test_arm64_only_main_binary_is_refused_for_universal2(
    tmp_path: Path, lipo: str
) -> None:
    app = make_app(
        tmp_path,
        python=("x86_64", "arm64"),
        libs={"objc/_objc.cpython-312-darwin.so": ("x86_64", "arm64")},
    )
    result = run_check(app, "arm64 x86_64", lipo)
    assert result.returncode == 1
    assert "Contents/MacOS/FontSync" in result.stdout


@pytest.mark.parametrize(
    "args",
    [[], ["--expect", "arm64"], ["--expect", "", "x.app"], ["--bogus", "x.app"]],
)
def test_usage_errors_exit_2(args: list[str]) -> None:
    result = subprocess.run(
        ["bash", str(CHECK_ARCHS), *args], capture_output=True, check=False, text=True
    )
    assert result.returncode == 2


# --- check-appcast-arch.py ----------------------------------------------------

APPCAST = """<?xml version="1.0" standalone="yes"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">
  <channel>
    <title>FontSync</title>
    <item>
      <title>0.1.2</title>
      <sparkle:version>3</sparkle:version>
      <sparkle:shortVersionString>0.1.2</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>14.0</sparkle:minimumSystemVersion>
      {requirement}
      <enclosure url="https://example.invalid/FontSync-0.1.2.dmg" length="1" type="application/octet-stream" sparkle:edSignature="x"/>
    </item>
    <item>
      <title>0.1.1</title>
      <sparkle:version>2</sparkle:version>
      <sparkle:shortVersionString>0.1.1</sparkle:shortVersionString>
      <enclosure url="https://example.invalid/FontSync-0.1.1.dmg" length="1" type="application/octet-stream" sparkle:edSignature="x"/>
    </item>
  </channel>
</rss>
"""

REQ = "<sparkle:hardwareRequirements>{}</sparkle:hardwareRequirements>"


def appcast(tmp_path: Path, requirement: str) -> Path:
    path = tmp_path / "appcast.xml"
    path.write_text(APPCAST.format(requirement=requirement))
    return path


def run_appcast(
    path: Path, version: str, mode: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_APPCAST), str(path), version, mode],
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.mark.parametrize(
    "value", ["arm64", " ARM64 ", "arm64,fakerequirement", "x86_64 arm64", "foo\tarm64"]
)
def test_appcast_arm64_requirement_accepted(tmp_path: Path, value: str) -> None:
    result = run_appcast(appcast(tmp_path, REQ.format(value)), "0.1.2", "--arm64-only")
    assert result.returncode == 0, result.stdout + result.stderr


def test_appcast_without_requirement_refused_for_arm64_build(tmp_path: Path) -> None:
    result = run_appcast(appcast(tmp_path, ""), "0.1.2", "--arm64-only")
    assert result.returncode == 1
    assert "hardwareRequirements" in result.stdout + result.stderr


def test_appcast_requirement_refused_for_universal_build(tmp_path: Path) -> None:
    result = run_appcast(appcast(tmp_path, REQ.format("arm64")), "0.1.2", "--universal")
    assert result.returncode == 1


def test_appcast_universal_build_without_requirement_passes(tmp_path: Path) -> None:
    result = run_appcast(appcast(tmp_path, ""), "0.1.2", "--universal")
    assert result.returncode == 0, result.stdout + result.stderr


def test_appcast_only_checks_the_released_version(tmp_path: Path) -> None:
    # 0.1.1 (universelle, sans exigence) reste dans le flux : ce n'est pas un écart.
    path = appcast(tmp_path, REQ.format("arm64"))
    assert run_appcast(path, "0.1.2", "--arm64-only").returncode == 0
    assert run_appcast(path, "0.1.1", "--arm64-only").returncode == 1


def test_appcast_missing_version_refused(tmp_path: Path) -> None:
    result = run_appcast(
        appcast(tmp_path, REQ.format("arm64")), "9.9.9", "--arm64-only"
    )
    assert result.returncode == 1
    assert "9.9.9" in result.stdout + result.stderr


@pytest.mark.parametrize("value", ["arm64 x86_64", "x86_64,\tARM64"])
def test_appcast_requirement_split_like_sparkle(tmp_path: Path, value: str) -> None:
    """Le client Sparkle découpe sur virgules ET blancs : arm64 y est exigé."""
    path = appcast(tmp_path, REQ.format(value))
    assert run_appcast(path, "0.1.2", "--universal").returncode == 1
    assert run_appcast(path, "0.1.2", "--arm64-only").returncode == 0


def test_appcast_duplicate_items_refused(tmp_path: Path) -> None:
    text = APPCAST.format(requirement=REQ.format("arm64"))
    first = text.index("<item>")
    second = text.index("<item>", first + 1)
    path = tmp_path / "appcast.xml"
    path.write_text(text[:second] + text[first:second] + text[second:])
    result = run_appcast(path, "0.1.2", "--arm64-only")
    assert result.returncode == 1
    assert "found 2" in result.stderr


def test_appcast_unreadable_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "appcast.xml"
    bad.write_text("<rss><channel>")
    assert run_appcast(bad, "0.1.2", "--arm64-only").returncode == 2
    assert run_appcast(tmp_path / "absent.xml", "0.1.2", "--arm64-only").returncode == 2


# --- câblage dans release-macos-app.sh ----------------------------------------


def test_release_script_wires_the_checks() -> None:
    script = RELEASE.read_text()
    xcodebuild = script[script.index("xcodebuild \\") : script.index("APP=")]
    assert 'ARCHS="$APP_ARCHS"' in xcodebuild
    assert "ONLY_ACTIVE_ARCH=NO" in xcodebuild

    # Le contrôle lipo passe après l'embarquement de l'agent, avant toute
    # signature, et bloque (set -e, pas de `|| true`).
    embed = script.index('cp -R "$BUILD_DIR/agent-venv" "$RES_VENV"')
    check = script.index('scripts/lib/check-archs.sh" --expect "$APP_ARCHS" "$APP"')
    first_sign = script.index('sign --entitlements "$PY_ENTS"')
    assert embed < check < first_sign
    assert "||" not in script[check : script.index("\n", check)]

    # L'appcast est vérifié juste après sa génération, par un vrai appel (pas
    # un `:` ni un `|| true`), sur la version publiée et dans le mode de l'arche.
    generate = script.index('"$SPARKLE_BIN/generate_appcast"')
    call = (
        'python3 "$REPO_ROOT/scripts/lib/check-appcast-arch.py" '
        '"$DIST_DIR/appcast.xml" "$VERSION" "$appcast_mode"\n'
    )
    assert script.count(call) == 1
    appcast_check = script.index(call)
    assert generate < appcast_check
    assert (
        script[script.rindex("\n", 0, appcast_check) + 1 : appcast_check].strip() == ""
    )
    assert (
        'if [[ "$ARCH" == "universal2" ]]; then appcast_mode=--universal; '
        "else appcast_mode=--arm64-only; fi"
    ) in script[generate:appcast_check]


def test_release_script_defaults_to_apple_silicon() -> None:
    script = RELEASE.read_text()
    host = script[script.index("  host)") : script.index(";;", script.index("  host)"))]
    assert 'APP_ARCHS="arm64"' in host
    assert 'uname -m)" == "arm64"' in host
    assert 'universal2) APP_ARCHS="arm64 x86_64"' in script
    assert 'ARCH="${ARCH:-host}"' in script


# --- exécution réelle de release-macos-app.sh (outils factices) ---------------
#
# Les tests de câblage ci-dessus lisent le script ; ceux-ci l'exécutent sur une
# copie du dépôt, avec de faux xcodebuild/codesign/hdiutil/generate_appcast :
# un contrôle commenté, passé en arrière-plan ou contourné ne bloquerait plus.

FAKE_TOOL = f"""#!{sys.executable}
import json, os, shutil, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps([name, *args]) + "\\n")
bins = Path(os.environ["FAKE_BINS"])

def put(dest, archs):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bins / "-".join(sorted(archs.split())), dest)
    dest.chmod(0o755)

if name == "security":
    print('  1) 0123456789ABCDEF "Developer ID Application: Test (TEAM)"')
elif name == "uname":
    if args == ["-m"]:
        print(os.environ.get("FAKE_UNAME", "arm64"))
    else:
        os.execv("/usr/bin/uname", ["uname", *args])
elif name == "file":
    print(f"{{args[-1]}}: Mach-O 64-bit executable")
elif name == "create-dmg":
    Path(args[-2]).write_bytes(b"dmg")
elif name == "build-agent-venv.sh":
    out = Path(args[args.index("--out") + 1])
    agent = os.environ.get("FAKE_AGENT_ARCHS", "arm64")
    put(out / "bin" / "python3.12", agent)
    put(out / "lib" / "python3.12" / "site-packages" / "_x.cpython-312-darwin.so",
        os.environ.get("FAKE_SO_ARCHS", agent))
elif name == "xcodebuild":
    archs = next(a for a in args if a.startswith("ARCHS="))[len("ARCHS="):]
    derived = Path(args[args.index("-derivedDataPath") + 1])
    put(derived / "Build/Products/Release/FontSync.app/Contents/MacOS/FontSync", archs)
    tools = Path(args[args.index("-clonedSourcePackagesDirPath") + 1])
    tools = tools / "artifacts" / "sparkle" / "Sparkle" / "bin"
    tools.mkdir(parents=True, exist_ok=True)
    for tool in ("generate_appcast", "sign_update"):
        shutil.copyfile(sys.argv[0], tools / tool)
        (tools / tool).chmod(0o755)
elif name == "generate_appcast":
    req = os.environ.get("FAKE_HWREQ", "arm64")
    req = f"<sparkle:hardwareRequirements>{{req}}</sparkle:hardwareRequirements>" if req else ""
    version = os.environ["VERSION"]
    (Path(args[-1]) / "appcast.xml").write_text(
        '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" '
        f'version="2.0"><channel><item><sparkle:shortVersionString>{{version}}'
        f'</sparkle:shortVersionString>{{req}}<enclosure url="x" length="3"/>'
        "</item></channel></rss>"
    )
elif name == "sign_update":
    print('sparkle:edSignature="x" length="3"')
"""


class Release:
    def __init__(self, tmp: Path, lipo: str) -> None:
        self.repo = tmp / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / "macos-app").mkdir()
        shutil.copy2(RELEASE, self.repo / "scripts" / RELEASE.name)
        shutil.copytree(CHECK_ARCHS.parent, self.repo / "scripts" / "lib")
        self.bin = tmp / "bin"
        self.bin.mkdir()
        tool = tmp / "fake-tool"
        tool.write_text(FAKE_TOOL)
        tool.chmod(0o755)
        for name in ("security", "uname", "file", "create-dmg", "xcodebuild"):
            (self.bin / name).symlink_to(tool)
        for name in ("codesign", "spctl"):
            (self.bin / name).symlink_to(tool)
        (self.repo / "scripts" / "build-agent-venv.sh").symlink_to(tool)
        (self.bin / "lipo").symlink_to(lipo)
        (self.bin / "python3").symlink_to(sys.executable)
        self.bins = tmp / "bins"
        self.bins.mkdir()
        for archs in (("arm64",), ("x86_64",), ("arm64", "x86_64")):
            (self.bins / "-".join(archs)).write_bytes(binary(*archs))
        self.log = tmp / "calls.log"
        self.log.touch()
        self.tmp = tmp

    def run(self, **env: str) -> subprocess.CompletedProcess[str]:
        full = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.tmp),
            "TMPDIR": str(self.tmp),
            "FAKE_LOG": str(self.log),
            "FAKE_BINS": str(self.bins),
            "VERSION": "0.1.2",
            "BUILD": "6",
            "DEVELOPER_ID_APP": "Developer ID Application: Test",
            "TEAM_ID": "TEAM",
            "SKIP_NOTARIZE": "1",
        }
        full.update(env)
        return subprocess.run(
            ["bash", str(self.repo / "scripts" / RELEASE.name)],
            env=full,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def calls(self, name: str) -> list[list[str]]:
        rows = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [row[1:] for row in rows if row[0] == name]


@pytest.fixture
def release(tmp_path: Path, lipo: str) -> Release:
    return Release(tmp_path, lipo)


def test_release_run_arm64_default(release: Release) -> None:
    result = release.run()
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    (build,) = release.calls("xcodebuild")
    assert "ARCHS=arm64" in build and "ONLY_ACTIVE_ARCH=NO" in build
    assert "Architectures OK" in out
    assert release.calls("generate_appcast")
    assert "hardware requirement consistent" in out
    assert release.calls("codesign")


def test_release_run_blocks_x86_64_library_before_signing(release: Release) -> None:
    result = release.run(FAKE_SO_ARCHS="x86_64")
    assert result.returncode != 0
    assert "_x.cpython-312-darwin.so" in result.stdout
    assert release.calls("codesign") == []
    assert release.calls("create-dmg") == []


def test_release_run_blocks_feed_without_requirement(release: Release) -> None:
    result = release.run(FAKE_HWREQ="")
    assert result.returncode != 0
    assert "hardwareRequirements" in result.stderr


def test_release_run_refuses_intel_host(release: Release) -> None:
    result = release.run(FAKE_UNAME="x86_64")
    assert result.returncode != 0
    assert release.calls("xcodebuild") == []


def test_release_run_universal2(release: Release) -> None:
    result = release.run(
        ARCH="universal2", FAKE_AGENT_ARCHS="arm64 x86_64", FAKE_HWREQ=""
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (build,) = release.calls("xcodebuild")
    assert "ARCHS=arm64 x86_64" in build
