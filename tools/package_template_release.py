from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


DEFAULT_EXCLUDES = (
    "*__pycache__/*",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
)


def _read_project_version(pyproject_path: Path) -> str:
    in_project = False
    content = pyproject_path.read_text(encoding="utf-8")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if not in_project:
            continue
        match = re.match(r'^version\s*=\s*"([^"]+)"\s*$', line)
        if match:
            return match.group(1)
    raise RuntimeError("Cannot read [project].version from pyproject.toml")


def _should_skip(rel_path: str, excludes: tuple[str, ...]) -> bool:
    for pattern in excludes:
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(
            rel_path.lower(), pattern.lower()
        ):
            return True
    return False


def _create_template_zip(repo_root: Path, output_zip: Path) -> int:
    template_root = repo_root / "template"
    if not template_root.exists():
        print("Missing template/ directory.", file=sys.stderr)
        return 1

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with ZipFile(output_zip, "w", compression=ZIP_DEFLATED) as zf:
        for path in sorted(template_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(template_root).as_posix()
            if _should_skip(rel, DEFAULT_EXCLUDES):
                continue
            zf.write(path, arcname=rel)
            added += 1

    if added == 0:
        print("Template archive is empty.", file=sys.stderr)
        return 1

    print(f"Created template archive: {output_zip}")
    print(f"Files in archive: {added}")
    return 0


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    version = _read_project_version(repo_root / "pyproject.toml")
    output_dir = (repo_root / "dist" / "release").resolve()
    output_zip = output_dir / f"wrapper-python-v{version}.zip"
    return _create_template_zip(repo_root, output_zip)


if __name__ == "__main__":
    raise SystemExit(main())
