#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Leo Durand
#
# This file is part of FontSync, a self-hosted font manager.
"""Check the appcast item of a release for its arm64 hardware requirement (M-21).

Usage: check-appcast-arch.py APPCAST VERSION (--arm64-only | --universal)

Sparkle 2.9+ `generate_appcast` adds `<sparkle:hardwareRequirements>arm64` by
itself when the app's main binary has no x86_64 slice (and the minimum system
is below macOS 27). The release script relies on that rather than editing the
feed afterwards — a later edit would break a signed feed — and this check makes
the reliance explicit: the item for VERSION must carry the requirement for an
Apple-silicon-only build, and must not for a universal one. Older items in the
same feed are left alone.

Exit status: 0 when consistent, 1 on a mismatch or a missing item, 2 when the
feed cannot be read.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET

SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"


def item_version(item: ET.Element) -> str | None:
    """Return the item's short version (element, or legacy enclosure attribute)."""
    element = item.find(f"{SPARKLE}shortVersionString")
    if element is not None and element.text:
        return element.text.strip()
    enclosure = item.find("enclosure")
    if enclosure is not None:
        return enclosure.get(f"{SPARKLE}shortVersionString")
    return None


def requirements(item: ET.Element) -> set[str]:
    element = item.find(f"{SPARKLE}hardwareRequirements")
    if element is None or not element.text:
        return set()
    # Same tokenisation as the Sparkle client (SUAppcastItem.m): commas and
    # whitespace, case-insensitive.
    return {part.lower() for part in re.split(r"[\s,]+", element.text) if part}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("appcast")
    parser.add_argument("version")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--arm64-only", action="store_true")
    mode.add_argument("--universal", action="store_true")
    args = parser.parse_args(argv)

    try:
        root = ET.parse(args.appcast).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"appcast unreadable: {args.appcast}: {exc}", file=sys.stderr)
        return 2

    items = [i for i in root.iter("item") if item_version(i) == args.version]
    if len(items) != 1:
        print(
            f"appcast: expected one item for {args.version}, found {len(items)}",
            file=sys.stderr,
        )
        return 1

    has_arm64 = "arm64" in requirements(items[0])
    if args.arm64_only and not has_arm64:
        print(
            f"appcast: {args.version} lacks <sparkle:hardwareRequirements>arm64 — "
            "Intel Macs would be offered an update that cannot run.",
            file=sys.stderr,
        )
        return 1
    if args.universal and has_arm64:
        print(
            f"appcast: {args.version} requires arm64 but the build is universal "
            "— Intel Macs would never be offered it.",
            file=sys.stderr,
        )
        return 1
    print(f"appcast: {args.version} hardware requirement consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
