#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path


def parse_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if match is None:
        raise ValueError(f"Unsupported version format: {value!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump(version: tuple[int, int, int], level: str) -> tuple[int, int, int]:
    major, minor, patch = version
    if level == "major":
        return major + 1, 0, 0
    if level == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump semantic version in pyproject.toml.")
    parser.add_argument("level", choices=["major", "minor", "patch"])
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path("pyproject.toml"),
        help="Path to pyproject.toml",
    )
    parser.add_argument(
        "--changelog",
        type=Path,
        default=Path("CHANGELOG.md"),
        help="Path to changelog",
    )
    args = parser.parse_args()

    pyproject_text = args.pyproject.read_text()
    pattern = re.compile(r'(?m)^version = "(\d+\.\d+\.\d+)"$')
    match = pattern.search(pyproject_text)
    if match is None:
        raise RuntimeError("Cannot find version in pyproject.toml")

    current = parse_version(match.group(1))
    new_version = bump(current, args.level)
    new_version_text = ".".join(str(part) for part in new_version)

    updated_pyproject = pattern.sub(f'version = "{new_version_text}"', pyproject_text, count=1)
    args.pyproject.write_text(updated_pyproject)

    if args.changelog.exists():
        changelog_text = args.changelog.read_text()
    else:
        changelog_text = (
            "# Changelog\n\n"
            "All notable changes to this project are documented in this file.\n"
        )

    release_header = f"## [{new_version_text}] - {date.today().isoformat()}"
    if release_header not in changelog_text:
        insertion = f"\n{release_header}\n\n### Added\n\n- TBD\n"
        marker = "All notable changes to this project are documented in this file."
        if marker in changelog_text:
            changelog_text = changelog_text.replace(marker, marker + insertion, 1)
        else:
            changelog_text += insertion
        args.changelog.write_text(changelog_text)

    print(f"Bumped version: {match.group(1)} -> {new_version_text}")


if __name__ == "__main__":
    main()
