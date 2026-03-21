from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _resolve_wheel(dist_dir: Path, version: str) -> Path | None:
    candidates = sorted(dist_dir.glob(f"hackarena3-{version}-*.whl"))
    if not candidates:
        return None
    return candidates[0]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    version = _read_project_version(repo_root / "pyproject.toml")
    dist_dir = repo_root / "dist"
    release_dir = dist_dir / "release"

    wheel_path = _resolve_wheel(dist_dir, version)
    zip_path = release_dir / f"wrapper-python-v{version}.zip"
    output_path = release_dir / "SHA256SUMS.txt"

    files: list[Path] = []
    if wheel_path is not None and wheel_path.is_file():
        files.append(wheel_path)
    if zip_path.is_file():
        files.append(zip_path)

    if not files:
        print(
            "No release artifacts found. Build wheel and package template first.",
            file=sys.stderr,
        )
        return 1

    lines = [f"{_sha256_file(path)}  {path.name}" for path in files]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote checksums: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
