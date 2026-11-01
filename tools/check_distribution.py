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
        modules = ("__init__.py", "core.py", "ir.py", "cli.py", "_serialization.py", "_state.py",
                   "logical_ir.py", "encoding.py", "equivalence.py", "verification.py", "verify_cli.py", "search.py",
                   "resources.py", "evaluation.py", "comparison.py", "search_verification.py",
                   "search_report.py", "_version.py", "search_cli.py", "hardware_models.py", "hardware_costs.py",
                   "hardware_report.py", "hardware.py")
        for module in modules:
            if f"q3hash/{module}" not in names:
                raise RuntimeError(f"Wheel is missing module {module}")
        package_modules = {name for name in names if name.startswith("q3hash/") and name.endswith(".py")}
        if package_modules != {f"q3hash/{module}" for module in modules}:
            raise RuntimeError("Wheel includes unexpected modules; clean stale build output")
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
        "docs/adr/0001-verified-encoding-first.md", "docs/contracts/logical-ir-and-encoding-v1.md",
        "docs/contracts/operator-verification-v1.md", "tests/test_contracts.py", "tests/test_equivalence.py",
        "benchmarks/README.md", "tests/test_semantics.py",
        "tools/check_distribution.py", "tools/check_numerics.py",
        "examples/qutrit.q3", "examples/mixed.q3", "examples/bell.q3",
        "examples/qutrit-entangled.q3", "examples/mixed-entangled.q3",
        "examples/logical-qutrit-shift.q3", "examples/physical-qutrit-shift-binary.q3",
        "examples/qutrit-binary.encoding.json", "tools/check_encoding.py",
        "docs/contracts/encoding-search-v1.md", "docs/plans/v0.4-implementation.md",
        "benchmarks/encoding-search-v1.json", "tools/check_search_contract.py",
        "src/q3hash/search.py", "tests/test_search_models.py", "tests/test_search_generation.py",
        "tools/check_search_generation.py",
        "src/q3hash/resources.py", "src/q3hash/evaluation.py", "src/q3hash/comparison.py",
        "src/q3hash/search_verification.py", "tests/test_resources.py", "tests/test_comparison.py",
        "tools/check_resources_comparison.py",
        "src/q3hash/search_report.py", "src/q3hash/_version.py",
        "tests/test_search_verification.py", "tests/test_search_report.py", "tools/check_search_evaluation.py",
        "src/q3hash/search_cli.py", "tests/test_search_cli.py", "tools/check_search.py",
        "examples/qutrit-native.encoding.json", "examples/qutrit-search.constraints.json",
        "benchmarks/search-cli-v1.json", "docs/search-cli.md",
        "docs/contracts/hardware-profile-v1.md", "docs/plans/v0.5-implementation.md",
        "benchmarks/hardware-cost-v1.json", "tools/check_hardware_contract.py",
        "src/q3hash/hardware_models.py", "tests/test_hardware_models.py",
        "tools/check_external_operators.py", "docs/hardware-profiles.md",
        "src/q3hash/hardware_costs.py", "tests/test_hardware_costs.py",
        "tools/check_hardware_costs.py", "docs/hardware-costs.md",
        "src/q3hash/hardware_report.py", "src/q3hash/hardware.py", "tests/test_hardware_report.py",
        "tools/check_hardware_reports.py", "docs/hardware-reports.md",
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
    verifier = binaries / ("q3hash-verify.exe" if os.name == "nt" else "q3hash-verify")
    search = binaries / ("q3hash-search.exe" if os.name == "nt" else "q3hash-search")
    run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], source, environment)
    check = (
        "import importlib.metadata,pathlib,sys,q3hash;"
        "p=pathlib.Path(q3hash.__file__).resolve();"
        "assert p.is_relative_to(pathlib.Path(sys.prefix).resolve()),p;"
        f"assert importlib.metadata.version('q3hash')=={version!r};"
        f"assert q3hash.__version__=={version!r};"
        "print('Installed package:',p)"
    )
    print(run([str(python), "-I", "-c", check], source, environment).strip())
    run([str(python), "-I", "-m", "compileall", "-q",
         str(destination / ("Lib/site-packages" if os.name == "nt" else
             f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages") / "q3hash")],
        source, environment)
    output = run([str(python), "-I", "-m", "unittest", "discover", "-s", "tests", "-v"], source, environment)
    print("\n".join(output.strip().splitlines()[-4:]))
    examples = sorted((source / "examples").glob("*.q3"))
    for example in examples:
        run([str(python), "-I", "-m", "q3hash.cli", str(example), "--amplitudes"], source, environment)
        run([str(console), str(example)], source, environment)
    for command in ([str(python), "-I", "-m", "q3hash.verify_cli"], [str(verifier)]):
        output = run(command + ["examples/logical-qutrit-shift.q3", "examples/physical-qutrit-shift-binary.q3",
                                "--encoding", "examples/qutrit-binary.encoding.json"], source, environment)
        if "verification: pass" not in output or "q3hash-circuit" not in output:
            raise RuntimeError("Installed full-subspace verifier failed its explicit circuit example")
    run([str(python), "-m", "pip", "check"], source, environment)
    print(f"All {len(examples)} examples passed through both simulator CLI entry points; dependencies are consistent.")
    print("Complete operator verification passed through module and console entry points.")
    print(run([str(python), "-I", "tools/check_search_contract.py"], source, environment).strip())
    print(run([str(python), "-I", "tools/check_search_generation.py"], source, environment).strip())
    print(run([str(python), "-I", "tools/check_resources_comparison.py"], source, environment).strip())
    print(run([str(python), "-I", "tools/check_search_evaluation.py"], source, environment).strip())
    print(run([str(python), "-I", "tools/check_search.py", "--console", str(search), "--isolated"], source, environment).strip())
    print(run([str(python), "-I", "tools/check_hardware_contract.py"], source, environment).strip())
    print(run([str(python), "-I", "tools/check_hardware_costs.py"], source, environment).strip())
    print(run([str(python), "-I", "tools/check_hardware_reports.py"], source, environment).strip())


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
