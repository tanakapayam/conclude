#!/usr/bin/env python3
"""Release checks for the conclude Python package (standard library only).

This is the Python counterpart of node/scripts/registry.mjs, and it is what
.github/workflows/python-publish.yml runs. GitHub Packages has no PyPI registry, so the
"stage" of a Python release is not a registry: it is these checks, run on the exact files
that will be uploaded.

    release.py integrity DIST                 print one digest that stands for every file in DIST
    release.py check-integrity DIST DIGEST    fail unless DIST still has that digest
    release.py verify-install DIST            install the wheel and the sdist into fresh virtual
                                              environments, check their contents against the
                                              source tree, and smoke-test what got installed
    release.py rehearsal-version ...          the throwaway version a rehearsal builds under
    release.py verify-published DIST ...      after uploading: wait for the index to list the
                                              files, compare its hashes with DIST's, download
                                              them again, and install the package back from it

Why one digest: what was checked is byte-for-byte what is uploaded. The build job computes it
once, the stage job and the publish job each recompute it from the artifact they downloaded,
and a mismatch stops the release.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import venv
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path

PACKAGE = "conclude"
SOURCE_ROOT = Path(__file__).resolve().parent.parent  # python/, where src/ and pyproject.toml live

# Run inside a fresh environment, with `-I` (isolated: no PYTHON* variables, no current
# directory on sys.path), so it can only be exercising what pip installed there.
SMOKE = """
import pathlib
import shlex
import sys

import conclude
from conclude import App, opt

expected = sys.argv[1]
assert conclude.__version__ == expected, f"version {conclude.__version__}, expected {expected}"
package_dir = pathlib.Path(conclude.__file__).resolve().parent
assert "site-packages" in package_dir.parts, f"imported from {package_dir}, not the install"
assert (package_dir / "py.typed").exists(), "py.typed is missing"

app = App(
    "smoke",
    {"cache": True, "debug": False, "verbose": opt(bool)},
    config_home_path=None,
    config_cwd_path=None,
)
parser = app.build_arg_parser(prog="smoke")


def parse(argv):
    namespace = parser.parse_args(argv)
    return {key: value for key, value in vars(namespace).items() if value is not None}


resolved = app.resolve(parse(["--no-cache", "--debug"]))
assert resolved["cache"] is False and resolved["debug"] is True, resolved
line = app.format_invocation(resolved, prog="smoke")
assert line == "smoke --no-cache --debug", line
assert app.resolve(parse(shlex.split(line)[1:])) == resolved, "an invocation does not read back"
print(f"conclude {conclude.__version__} from {package_dir}: ok")
"""


class ReleaseError(Exception):
    """A check failed; the message says what to look at."""


# --- the artifacts ------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifacts(dist: Path) -> dict[str, Path]:
    """``{"wheel": ..., "sdist": ...}``: a build leaves exactly one of each."""
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ReleaseError(
            f"{dist} should hold exactly one wheel and one sdist, "
            f"found {[p.name for p in (*wheels, *sdists)] or 'nothing'}"
        )
    return {"wheel": wheels[0], "sdist": sdists[0]}


def manifest(dist: Path) -> list[tuple[str, str]]:
    """``(sha256, filename)`` for every file in ``dist``, sorted by name."""
    files = artifacts(dist)
    return sorted((sha256_file(path), path.name) for path in files.values())


def integrity(dist: Path) -> str:
    """One digest for the whole set: it changes if any file, or its name, does."""
    text = "".join(f"{digest}  {name}\n" for digest, name in manifest(dist))
    return "sha256-" + hashlib.sha256(text.encode()).hexdigest()


def check_integrity(dist: Path, expected: str) -> None:
    actual = integrity(dist)
    if actual != expected:
        raise ReleaseError(
            f"the distributions are not the ones that were built (built {expected}, here {actual})"
        )


def version_of(dist: Path) -> str:
    """The version the wheel and the sdist agree on (their file names say it)."""
    files = artifacts(dist)
    wheel = files["wheel"].name.split("-")
    sdist = files["sdist"].name.removesuffix(".tar.gz").split("-", 1)
    if wheel[0] != PACKAGE or sdist[0] != PACKAGE:
        raise ReleaseError(
            f"expected {PACKAGE} distributions, found {list(map(str, files.values()))}"
        )
    if wheel[1] != sdist[1]:
        raise ReleaseError(f"the wheel is {wheel[1]} but the sdist is {sdist[1]}")
    return wheel[1]


# --- contents -----------------------------------------------------------------------------


def expected_files(source_root: Path) -> set[str]:
    """Every file of the package in the source tree, relative to the package directory."""
    package = source_root / "src" / PACKAGE
    return {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def archive_files(path: Path, root: str) -> set[str]:
    """The package's files inside a wheel (``root`` is ``conclude``) or an sdist."""
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    else:
        with tarfile.open(path) as archive:
            names = [name.split("/", 1)[1] for name in archive.getnames() if "/" in name]
    prefix = root + "/"
    return {
        name[len(prefix) :] for name in names if name.startswith(prefix) and not name.endswith("/")
    }


def check_contents(dist: Path, source_root: Path) -> list[str]:
    """Problems with what the wheel and the sdist hold. The wheel is the case that matters:
    0.1.0 of the Node package shipped without its build output, and a wheel that leaves out
    a new module would import fine from a checkout and fail for everyone else."""
    files = artifacts(dist)
    wanted = expected_files(source_root)
    problems = []
    for kind, root in (("wheel", PACKAGE), ("sdist", f"src/{PACKAGE}")):
        have = archive_files(files[kind], root)
        for name in sorted(wanted - have):
            problems.append(f"the {kind} is missing {PACKAGE}/{name}")
        for name in sorted(have - wanted):
            problems.append(f"the {kind} has {PACKAGE}/{name}, which is not in the source tree")
    return problems


# --- virtual environments -----------------------------------------------------------------


def run(command: Sequence[str | Path], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command], check=False, capture_output=True, text=True, cwd=cwd
    )


def make_venv(parent: Path, name: str) -> Path:
    """A fresh environment with pip; returns its interpreter."""
    target = parent / name
    venv.EnvBuilder(with_pip=True, clear=True).create(target)
    return target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def pip(python: Path, *arguments: str | Path) -> subprocess.CompletedProcess[str]:
    return run([python, "-m", "pip", "--disable-pip-version-check", *arguments])


def smoke(python: Path, version: str, scratch: Path) -> str:
    result = run([python, "-I", "-c", SMOKE, version], cwd=scratch)
    if result.returncode != 0:
        raise ReleaseError(f"the installed package failed its smoke test:\n{result.stderr.strip()}")
    return result.stdout.strip()


def verify_install(dist: Path, source_root: Path) -> None:
    version = version_of(dist)
    problems = check_contents(dist, source_root)
    if problems:
        raise ReleaseError("the distributions do not hold the package:\n  " + "\n  ".join(problems))
    print(f"contents: the wheel and the sdist both hold all of src/{PACKAGE}")

    files = artifacts(dist)
    with tempfile.TemporaryDirectory(prefix="conclude-release-") as scratch_name:
        scratch = Path(scratch_name)
        for kind, extra in (("wheel", ["--no-index"]), ("sdist", [])):
            # A wheel installs on its own: --no-index makes sure it is that very file. An sdist
            # has to build, so it may reach the index for hatchling.
            python = make_venv(scratch, f"venv-{kind}")
            installed = pip(python, "install", "--no-cache-dir", *extra, files[kind])
            if installed.returncode != 0:
                raise ReleaseError(f"pip could not install the {kind}:\n{installed.stderr.strip()}")
            print(f"{kind}: {smoke(python, version, scratch)}")


# --- rehearsal versions -------------------------------------------------------------------

VERSION_LINE = re.compile(r'^__version__ = "([^"]+)"$', re.M)


def read_version(source_root: Path) -> str:
    text = (source_root / "src" / PACKAGE / "__init__.py").read_text(encoding="utf-8")
    match = VERSION_LINE.search(text)
    if not match:
        raise ReleaseError("no __version__ in src/conclude/__init__.py")
    return match.group(1)


def rehearsal_version(base: str, run_number: int, run_attempt: int) -> str:
    """``1.1.0`` -> ``1.1.0.dev10001``: below the real release, so it never stands in for it,
    and different for every run and every re-run, so an index that refuses to take a file
    twice (TestPyPI never does, even after a delete) is never asked to."""
    if ".dev" in base:
        raise ReleaseError(f"{base} is already a development version")
    if not 1 <= run_attempt <= 99:
        raise ReleaseError(f"run attempt {run_attempt} is outside 1..99")
    return f"{base}.dev{run_number * 100 + run_attempt}"


def write_version(source_root: Path, version: str) -> None:
    path = source_root / "src" / PACKAGE / "__init__.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(VERSION_LINE.sub(f'__version__ = "{version}"', text, count=1), encoding="utf-8")


# --- after the upload ---------------------------------------------------------------------


def fetch(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "conclude-release-check"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


def retrying(
    description: str, attempt: Callable[[], str | None], attempts: int, delay: float
) -> None:
    """Call ``attempt`` until it returns ``None`` (done). A string is "not yet, because ...":
    a fresh upload takes a while to show up on the index and its CDN, so that is retried;
    a ``ReleaseError`` raised from inside is final."""
    reason = "not tried"
    for number in range(1, attempts + 1):
        outcome = attempt()
        if outcome is None:
            return
        reason = outcome
        print(f"{description}: {reason} (attempt {number} of {attempts})")
        if number < attempts:
            time.sleep(delay)
    raise ReleaseError(f"{description}: still not there after {attempts} attempts: {reason}")


def published_files(index: str, version: str) -> dict[str, str] | None:
    """``{filename: sha256}`` the index lists for this version, or None if it has none yet."""
    status, body = fetch(f"{index}/pypi/{PACKAGE}/{version}/json")
    if status == 404:
        return None
    if status != 200:
        raise ReleaseError(f"{index} answered {status} for {PACKAGE} {version}")
    listed = json.loads(body)["urls"]
    return {item["filename"]: item["digests"]["sha256"] for item in listed}


def verify_published(
    dist: Path,
    index: str,
    *,
    expect_provenance: bool,
    attempts: int,
    delay: float,
) -> None:
    version = version_of(dist)
    local = {name: digest for digest, name in manifest(dist)}

    def listed() -> str | None:
        remote = published_files(index, version)
        if remote is None:
            return f"{index} lists no {PACKAGE} {version} yet"
        for name, digest in local.items():
            if name not in remote:
                return f"{name} is not listed yet"
            if remote[name] != digest:
                raise ReleaseError(
                    f"{name} on {index} is not the file that was built "
                    f"(built {digest}, listed {remote[name]})"
                )
        return None

    retrying("listing", listed, attempts, delay)
    print(f"listing: {index} has {', '.join(sorted(local))}, with the hashes that were built")

    with tempfile.TemporaryDirectory(prefix="conclude-published-") as scratch_name:
        scratch = Path(scratch_name)
        python = make_venv(scratch, "venv-download")

        def downloaded() -> str | None:
            for flag in ("--only-binary=:all:", "--no-binary=:all:"):
                target = scratch / f"download{flag.split('=')[0]}"
                result = pip(
                    python, "download", "--no-deps", "--no-cache-dir", flag,
                    "--index-url", f"{index}/simple/", "--dest", target, f"{PACKAGE}=={version}",
                )  # fmt: skip
                if result.returncode != 0:
                    return (
                        result.stderr.strip().splitlines()[-1]
                        if result.stderr.strip()
                        else "pip failed"
                    )
                for path in target.iterdir():
                    if path.name not in local:
                        raise ReleaseError(f"pip downloaded {path.name}, which was not built here")
                    if sha256_file(path) != local[path.name]:
                        raise ReleaseError(
                            f"the {path.name} that users download is not the one built"
                        )
            return None

        retrying("download", downloaded, attempts, delay)
        print("download: pip fetched the wheel and the sdist from the index; both match")

        def installed() -> str | None:
            fresh = make_venv(scratch, "venv-installed")
            result = pip(
                fresh, "install", "--no-cache-dir", "--index-url", f"{index}/simple/",
                f"{PACKAGE}=={version}",
            )  # fmt: skip
            if result.returncode != 0:
                return (
                    result.stderr.strip().splitlines()[-1]
                    if result.stderr.strip()
                    else "pip failed"
                )
            print(f"install: {smoke(fresh, version, scratch)}")
            return None

        retrying("install", installed, attempts, delay)

    if expect_provenance:
        for name in sorted(local):
            url = f"{index}/integrity/{PACKAGE}/{version}/{name}/provenance"

            def attested(url: str = url, name: str = name) -> str | None:
                status, body = fetch(url)
                if status == 404:
                    return f"no attestation for {name} yet"
                if status != 200:
                    raise ReleaseError(f"{index} answered {status} for the provenance of {name}")
                if not json.loads(body).get("attestation_bundles"):
                    raise ReleaseError(f"{name} has an empty provenance record")
                return None

            retrying(f"provenance of {name}", attested, attempts, delay)
        print("provenance: every file is attested")


# --- the command line ---------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--source-root", type=Path, default=SOURCE_ROOT, help="python/ (default: here)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("integrity").add_argument("dist", type=Path)

    check = commands.add_parser("check-integrity")
    check.add_argument("dist", type=Path)
    check.add_argument("expected")

    commands.add_parser("verify-install").add_argument("dist", type=Path)

    rehearsal = commands.add_parser("rehearsal-version")
    rehearsal.add_argument("--run-number", type=int, required=True)
    rehearsal.add_argument("--run-attempt", type=int, required=True)
    rehearsal.add_argument("--write", action="store_true", help="also set it in __init__.py")

    published = commands.add_parser("verify-published")
    published.add_argument("dist", type=Path)
    published.add_argument("--index", default="https://pypi.org", help="no trailing slash")
    published.add_argument("--expect-provenance", action="store_true")
    published.add_argument("--attempts", type=int, default=20)
    published.add_argument("--delay", type=float, default=15)

    args = parser.parse_args(argv)
    try:
        if args.command == "integrity":
            print(integrity(args.dist))
        elif args.command == "check-integrity":
            check_integrity(args.dist, args.expected)
            print(f"the distributions are the ones that were built ({args.expected})")
        elif args.command == "verify-install":
            verify_install(args.dist, args.source_root)
        elif args.command == "rehearsal-version":
            version = rehearsal_version(
                read_version(args.source_root), args.run_number, args.run_attempt
            )
            if args.write:
                write_version(args.source_root, version)
            print(version)
        else:
            verify_published(
                args.dist,
                args.index.rstrip("/"),
                expect_provenance=args.expect_provenance,
                attempts=args.attempts,
                delay=args.delay,
            )
    except ReleaseError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
