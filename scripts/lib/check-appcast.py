#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Leo Durand
"""Check that an appcast describes exactly the DMG about to be published (B-88, B-100).

Usage: check-appcast.py APPCAST --version V --dmg PATH --repo OWNER/NAME
                        [--build B] [--ed-signature SIG]

publish-release.sh runs this before sending anything to GitHub:
- exactly one item carries shortVersionString V;
- its enclosure is https://github.com/OWNER/NAME/releases/download/vV/<dmg name>
  (never `releases/latest/download/…`, which breaks as soon as another release
  becomes "latest"), its length is the DMG size, and it is EdDSA-signed;
- with --build, its sparkle:version is B; with --ed-signature (from
  `sign_update`), its signature matches;
- every other item points at its own versioned release as well.

Exit status: 0 when consistent, 1 on any mismatch, 2 when a file cannot be read.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"


def field(item: ET.Element, name: str) -> str | None:
    """Sparkle field as element, or legacy attribute on the enclosure."""
    element = item.find(f"{SPARKLE}{name}")
    if element is not None and element.text and element.text.strip():
        return element.text.strip()
    enclosure = item.find("enclosure")
    if enclosure is not None:
        value = enclosure.get(f"{SPARKLE}{name}")
        return value.strip() if value else None
    return None


def build_number(value: str | None) -> tuple[int, ...]:
    """Numeric build (CFBundleVersion, dot-separated); unparsable sorts first."""
    try:
        return tuple(int(part) for part in (value or "").split("."))
    except ValueError:
        return (-1,)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("appcast")
    parser.add_argument("--version", required=True)
    parser.add_argument("--dmg", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--build")
    parser.add_argument("--ed-signature")
    args = parser.parse_args(argv)

    try:
        root = ET.parse(args.appcast).getroot()
        size = Path(args.dmg).stat().st_size
    except (OSError, ET.ParseError) as exc:
        print(f"appcast: cannot read: {exc}", file=sys.stderr)
        return 2

    base = f"https://github.com/{args.repo}/releases/download/"
    errors: list[str] = []
    channel = root.find("channel")
    # Sparkle only reads rss/channel/item: an item elsewhere would be ignored.
    items = channel.findall("item") if channel is not None else []
    mine = [i for i in items if field(i, "shortVersionString") == args.version]
    if len(mine) != 1:
        errors.append(f"expected one item for {args.version}, found {len(mine)}")

    for item in items:
        version = field(item, "shortVersionString") or "?"
        # Main enclosure and delta enclosures alike (sparkle:deltas).
        enclosures = list(item.iter("enclosure")) or [ET.Element("enclosure")]
        for enclosure in enclosures:
            url = enclosure.get("url", "")
            if not url.startswith(f"{base}v{version}/"):
                errors.append(
                    f"item {version}: enclosure url {url or '(none)'} is not "
                    f"under {base}v{version}/"
                )

    if len(mine) == 1:
        item = mine[0]
        enclosure = item.find("enclosure")
        attrs = enclosure.attrib if enclosure is not None else {}
        expected_url = f"{base}v{args.version}/{Path(args.dmg).name}"
        if attrs.get("url") != expected_url:
            errors.append(
                f"item {args.version}: enclosure url {attrs.get('url')} "
                f"!= {expected_url}"
            )
        if attrs.get("length") != str(size):
            errors.append(
                f"item {args.version}: enclosure length {attrs.get('length')} "
                f"!= DMG size {size}"
            )
        signature = attrs.get(f"{SPARKLE}edSignature")
        if not signature:
            errors.append(f"item {args.version}: enclosure has no edSignature")
        elif args.ed_signature and signature != args.ed_signature:
            errors.append(
                f"item {args.version}: edSignature differs from sign_update's "
                "(appcast generated for another DMG?)"
            )
        mine_build = build_number(field(item, "version"))
        for other in items:
            if (
                other is not item
                and build_number(field(other, "version")) >= mine_build
            ):
                errors.append(
                    f"item {field(other, 'shortVersionString')}: build "
                    f"{field(other, 'version')} >= {args.version}'s "
                    f"{field(item, 'version')} (Sparkle would offer it instead)"
                )
        if args.build and field(item, "version") != args.build:
            errors.append(
                f"item {args.version}: sparkle:version (build) "
                f"{field(item, 'version')} != {args.build}"
            )

    for error in errors:
        print(f"appcast: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"appcast: {args.version} consistent with {Path(args.dmg).name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
