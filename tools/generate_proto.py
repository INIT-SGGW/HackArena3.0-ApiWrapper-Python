import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_IMPORT_REWRITES = (
    (
        re.compile(r"from achievement\.v1 import"),
        "from hackarena3.proto.achievement.v1 import",
    ),
    (re.compile(r"from auth\.v1 import"), "from hackarena3.proto.auth.v1 import"),
    (
        re.compile(r"from hackarena((?:\.[a-zA-Z0-9_]+)+) import"),
        r"from hackarena3.proto.hackarena\1 import",
    ),
    (re.compile(r"from race\.v1 import"), "from hackarena3.proto.race.v1 import"),
    (re.compile(r"from weather\.v1 import"), "from hackarena3.proto.weather.v1 import"),
)


@dataclass(frozen=True)
class _ProtoSource:
    proto_dir: Path
    paths: tuple[str, ...] = ()


def _rewrite_generated_imports(out_dir: Path) -> None:
    for path in out_dir.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".pyi"}:
            continue
        content = path.read_text(encoding="utf-8")
        rewritten = content
        for regex, replacement in _IMPORT_REWRITES:
            rewritten = regex.sub(replacement, rewritten)
        if rewritten != content:
            path.write_text(rewritten, encoding="utf-8")


def _handle_remove_readonly(
    func: Callable[..., Any], path: str, _exc_info: object
) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _build_generation_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    venv_bin_candidates = (
        repo_root / ".venv" / "Scripts",
        repo_root / ".venv" / "bin",
    )
    existing_path = env.get("PATH", "")
    prepend_parts = [str(path) for path in venv_bin_candidates if path.is_dir()]
    if prepend_parts:
        env["PATH"] = os.pathsep.join(
            [*prepend_parts, existing_path] if existing_path else prepend_parts
        )
    return env


def _run_buf_generate(
    source: _ProtoSource,
    tmp_dir: Path,
    buf_template: Path,
    env: dict[str, str],
) -> None:
    command = [
        "buf",
        "generate",
        str(source.proto_dir),
        "--template",
        str(buf_template),
        "--output",
        str(tmp_dir),
    ]
    for path in source.paths:
        command.extend(["--path", path])
    subprocess.run(command, check=True, env=env)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    proto_sources = (
        _ProtoSource(
            proto_dir=repo_root / "third_party" / "HackArena3.0-Proto" / "proto"
        ),
        _ProtoSource(proto_dir=repo_root / "third_party" / "HackArena-Proto" / "proto"),
    )
    out_dir = repo_root / "src" / "hackarena3" / "proto"
    buf_template = repo_root / "tools" / "buf.gen.python.yaml"

    for source in proto_sources:
        if not source.proto_dir.exists():
            raise RuntimeError(f"Proto repository not found: {source.proto_dir}\n")
    if not buf_template.is_file():
        raise RuntimeError(f"Buf template not found: {buf_template}")

    print("Generating Python protobuf stubs...")

    if out_dir.exists():
        shutil.rmtree(out_dir, onexc=_handle_remove_readonly)

    out_dir.mkdir(parents=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        env = _build_generation_env(repo_root)

        for source in proto_sources:
            _run_buf_generate(source, tmp_dir, buf_template, env)

        for item in tmp_dir.iterdir():
            dest = out_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

    (out_dir / "__init__.py").touch(exist_ok=True)
    for path in out_dir.rglob("*"):
        if path.is_dir():
            (path / "__init__.py").touch(exist_ok=True)

    _rewrite_generated_imports(out_dir)

    print("Proto generation finished.")


if __name__ == "__main__":
    main()
