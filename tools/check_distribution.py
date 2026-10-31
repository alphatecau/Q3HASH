"""Audit built wheel and source archives using isolated installed packages."""

import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile


def run(command, cwd, environment):
    result = subprocess.run(command, cwd=cwd, env=environment, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {command}\n{result.stdout}")
    return result.stdout


def inspect_wheel(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for module in ("__init__.py", "core.py", "ir.py", "cli.py"):
            if f"q3hash/{module}" not in names:
                raise RuntimeError(f"Wheel is missing module {module}")
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        if metadata["Name"] != "q3hash" or metadata["License-Expression"] != "Apache-2.0":
            raise RuntimeError("Incorrect package name or licence metadata")
        if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
            raise RuntimeError("Wheel does not contain the licence")
        record = next(name for name in names if name.endswith(".dist-info/RECORD"))
        for name, digest, size in csv.reader(io.StringIO(archive.read(record).decode())):
            if not digest:
                if name != record:
                    raise RuntimeError(f"Unhashed wheel member {name}")
                continue
            algorithm, expected = digest.split("=", 1)
            data = archive.read(name)
            actual = base64.urlsafe_b64encode(hashlib.new(algorithm, data).digest()).rstrip(b"=").decode()
            if actual != expected or len(data) != int(size):
                raise RuntimeError(f"Wheel RECORD mismatch: {name}")
    return metadata["Version"]


def extract_source(archive_path, destination):
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError(f"Invalid source archive path: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError(f"Unreadable source member: {member.name}")
                target.write_bytes(stream.read())
            else:
                raise RuntimeError(f"Unsupported source archive member: {member.name}")
    roots = list(destination.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise RuntimeError("Expected one source archive root")
    source = roots[0]
    required = [
        "LICENSE", "README.md", "CHANGELOG.md", "MANIFEST.in",
        "docs/language-spec.md", "docs/semantics.md", "docs/validation.md",
        "benchmarks/README.md", "tests/test_semantics.py",
        "tools/check_distribution.py", "tools/check_numerics.py",
        "examples/qutrit.q3", "examples/mixed.q3", "examples/bell.q3",
        "examples/qutrit-entangled.q3", "examples/mixed-entangled.q3",
    ]
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise RuntimeError(f"Source distribution is incomplete: {missing}")
    return source


def installed_checks(wheel, source, destination, version, environment):
    venv.EnvBuilder(with_pip=True).create(destination)
    binaries = destination / ("Scripts" if os.name == "nt" else "bin")
    python = binaries / ("python.exe" if os.name == "nt" else "python")
    console = binaries / ("q3hash.exe" if os.name == "nt" else "q3hash")
    run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], source, environment)
    check = (
        "import importlib.metadata,pathlib,sys,q3hash;"
        "p=pathlib.Path(q3hash.__file__).resolve();"
        "assert p.is_relative_to(pathlib.Path(sys.prefix).resolve()),p;"
        f"assert importlib.metadata.version('q3hash')=={version!r};"
        "print('Installed package:',p)"
    )
    print(run([str(python), "-I", "-c", check], source, environment).strip())
    run([str(python), "-I", "-m", "compileall", "-q",
         str(destination / ("Lib/site-packages" if os.name == "nt" else
             f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages") / "q3hash")],
        source, environment)
    output = run([str(python), "-I", "-m", "unittest", "discover", "-s", "tests", "-v"], source, environment)
    print("\n".join(output.strip().splitlines()[-4:]))
    for example in sorted((source / "examples").glob("*.q3")):
        run([str(python), "-I", "-m", "q3hash.cli", str(example), "--amplitudes"], source, environment)
        run([str(console), str(example)], source, environment)
    run([str(python), "-m", "pip", "check"], source, environment)
    print("All five examples passed through both CLI entry points; dependencies are consistent.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    args = parser.parse_args()
    artifacts = args.artifacts.resolve()
    wheels = list(artifacts.glob("*.whl"))
    sources = list(artifacts.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        parser.error("supply a directory containing exactly one wheel and one source archive")
    version = inspect_wheel(wheels[0])
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    with tempfile.TemporaryDirectory(prefix="q3hash-dist-") as directory:
        root = Path(directory)
        source = extract_source(sources[0], root / "source")
        print("Testing the published wheel outside the repository checkout")
        installed_checks(wheels[0], source, root / "wheel-env", version, environment)
        rebuilt = root / "rebuilt"
        rebuilt.mkdir()
        run([sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps",
             "--no-build-isolation", str(source), "--wheel-dir", str(rebuilt)], root, environment)
        rebuilt_wheels = list(rebuilt.glob("*.whl"))
        if len(rebuilt_wheels) != 1 or inspect_wheel(rebuilt_wheels[0]) != version:
            raise RuntimeError("Source distribution did not rebuild the expected wheel")
        print("Testing the wheel rebuilt solely from the source archive")
        installed_checks(rebuilt_wheels[0], source, root / "source-env", version, environment)
    print(f"Distribution audit passed for q3hash {version} on Python {sys.version.split()[0]}")


if __name__ == "__main__":
    main()
