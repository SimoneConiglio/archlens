from pathlib import Path

import pytest

from archlens import analyze

ROOT = Path(__file__).resolve().parents[1]
ZOO = ROOT / "examples" / "patterns_zoo"


@pytest.fixture(scope="session")
def zoo():
    return analyze(ZOO)


def write_pkg(tmp_path: Path, files: dict[str, str]) -> Path:
    pkg = tmp_path / "pkg"
    for name, src in files.items():
        f = pkg / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(src)
    if not (pkg / "__init__.py").exists():
        (pkg / "__init__.py").write_text("")
    return pkg
