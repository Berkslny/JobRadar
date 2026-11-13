"""Check that the engine package the app carries (JobRadar/jobradar-*.whl) was built from the current sources.

usage: check_wheel.py      exit code 1 and a list of differences when scripts/build-engine.command must be run again
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engine" / "src"


def main() -> int:
    wheels = sorted((ROOT / "JobRadar").glob("jobradar-*.whl"))
    if len(wheels) != 1:
        print(f"expected one engine package in JobRadar/, found {len(wheels)}")
        return 1
    with zipfile.ZipFile(wheels[0]) as z:
        packed = {n: z.read(n) for n in z.namelist() if n.startswith("jobradar/") and not n.endswith("/")}
    sources = {p.relative_to(SRC).as_posix(): p.read_bytes() for p in (SRC / "jobradar").rglob("*")
               if p.is_file() and "__pycache__" not in p.parts}
    problems = [f"not in the package: {n}" for n in sorted(sources.keys() - packed.keys())]
    problems += [f"only in the package: {n}" for n in sorted(packed.keys() - sources.keys())]
    problems += [f"differs: {n}" for n in sorted(sources.keys() & packed.keys()) if sources[n] != packed[n]]
    for line in problems:
        print(line)
    if problems:
        print(f"{wheels[0].name} is out of date: run scripts/build-engine.command")
        return 1
    print(f"{wheels[0].name} matches engine/src ({len(sources)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
