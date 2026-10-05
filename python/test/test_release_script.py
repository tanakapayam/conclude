"""The release checks in scripts/release.py, without a network or a package index.

Installing the artifacts and reading them back from PyPI are exercised where they can be real:
python-ci.yml runs verify-install on every build, and python-publish.yml runs the whole
sequence on a release. What is pinned down here is the logic around them -- the fingerprint,
the contents check, the rehearsal versions, and every way verify-published refuses.
"""

import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "release.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not part of this checkout")


@pytest.fixture(scope="module")
def release():
    spec = importlib.util.spec_from_file_location("release_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOURCE_FILES = ["__init__.py", "app.py", "cli.py", "py.typed"]


def make_source(root: Path, version: str = "1.1.0", files=SOURCE_FILES) -> Path:
    package = root / "src" / "conclude"
    package.mkdir(parents=True)
    for name in files:
        (package / name).write_text("", encoding="utf-8")
    (package / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "app.cpython-313.pyc").write_bytes(b"\0")
    return root


def make_dist(
    root: Path,
    version: str = "1.1.0",
    wheel_files=SOURCE_FILES,
    sdist_files=SOURCE_FILES,
    wheel_version=None,
) -> Path:
    dist = root / "dist"
    dist.mkdir(parents=True)
    wheel = dist / f"conclude-{wheel_version or version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in wheel_files:
            archive.writestr(f"conclude/{name}", f"wheel {name}")
        archive.writestr(f"conclude-{version}.dist-info/METADATA", "Name: conclude")
    sdist = dist / f"conclude-{version}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        for name in [*sdist_files, "../PKG-INFO"]:
            path = name if name.startswith("..") else f"src/conclude/{name}"
            data = f"sdist {name}".encode()
            info = tarfile.TarInfo(f"conclude-{version}/{path.removeprefix('../')}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return dist


# --- the fingerprint ---------------------------------------------------------------------


def test_the_fingerprint_is_stable_and_changes_with_any_byte(release, tmp_path):
    dist = make_dist(tmp_path)
    first = release.integrity(dist)
    assert first == release.integrity(dist)
    assert first.startswith("sha256-") and len(first) == len("sha256-") + 64

    wheel = next(dist.glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"\0")
    assert release.integrity(dist) != first


def test_the_fingerprint_depends_on_the_file_names_too(release, tmp_path):
    one = make_dist(tmp_path / "one")  # noqa: SIM115
    two = make_dist(tmp_path / "two", version="1.1.1")
    assert release.integrity(one) != release.integrity(two)


def test_check_integrity_accepts_the_built_files_and_refuses_anything_else(release, tmp_path):
    dist = make_dist(tmp_path)
    release.check_integrity(dist, release.integrity(dist))
    with pytest.raises(release.ReleaseError, match="not the ones that were built"):
        release.check_integrity(dist, "sha256-" + "0" * 64)


@pytest.mark.parametrize("extra", ["conclude-1.1.0-py3-none-any.whl.bak", "other.whl", "x.tar.gz"])
def test_a_dist_directory_must_hold_exactly_one_wheel_and_one_sdist(release, tmp_path, extra):
    dist = make_dist(tmp_path)
    if extra.endswith((".whl", ".tar.gz")):
        (dist / extra).write_bytes(b"")
        with pytest.raises(release.ReleaseError, match="exactly one wheel and one sdist"):
            release.integrity(dist)
    else:
        (dist / extra).write_bytes(b"")  # not a distribution: ignored
        release.integrity(dist)


def test_an_empty_dist_directory_is_an_error(release, tmp_path):
    (tmp_path / "dist").mkdir()
    with pytest.raises(release.ReleaseError, match="found nothing"):
        release.integrity(tmp_path / "dist")


def test_the_version_comes_from_the_file_names_and_they_must_agree(release, tmp_path):
    assert release.version_of(make_dist(tmp_path / "ok", version="1.1.0.dev10001")) == (
        "1.1.0.dev10001"
    )
    split = make_dist(tmp_path / "split", version="1.1.0", wheel_version="1.0.2")
    with pytest.raises(release.ReleaseError, match="wheel is 1.0.2 but the sdist is 1.1.0"):
        release.version_of(split)


# --- contents ----------------------------------------------------------------------------


def test_the_expected_files_are_the_source_trees_and_skip_bytecode(release, tmp_path):
    source = make_source(tmp_path)
    assert release.expected_files(source) == set(SOURCE_FILES)


def test_a_complete_build_has_no_content_problems(release, tmp_path):
    source = make_source(tmp_path / "src-tree")
    dist = make_dist(tmp_path / "build")
    assert release.check_contents(dist, source) == []


def test_a_wheel_that_leaves_out_a_new_module_is_caught(release, tmp_path):
    source = make_source(tmp_path / "src-tree")
    dist = make_dist(tmp_path / "build", wheel_files=["__init__.py", "app.py", "py.typed"])
    assert release.check_contents(dist, source) == ["the wheel is missing conclude/cli.py"]


def test_an_sdist_that_leaves_one_out_is_caught_too(release, tmp_path):
    source = make_source(tmp_path / "src-tree")
    dist = make_dist(tmp_path / "build", sdist_files=["__init__.py", "cli.py", "py.typed"])
    assert release.check_contents(dist, source) == ["the sdist is missing conclude/app.py"]


def test_a_stale_file_that_is_not_in_the_source_is_caught(release, tmp_path):
    source = make_source(tmp_path / "src-tree")
    dist = make_dist(tmp_path / "build", wheel_files=[*SOURCE_FILES, "old_module.py"])
    problems = release.check_contents(dist, source)
    assert problems == ["the wheel has conclude/old_module.py, which is not in the source tree"]


def test_dist_info_is_not_mistaken_for_package_files(release, tmp_path):
    dist = make_dist(tmp_path)
    wheel = next(dist.glob("*.whl"))
    assert release.archive_files(wheel, "conclude") == set(SOURCE_FILES)


# --- rehearsal versions ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "attempt", "expected"),
    [(101, 1, "1.1.0.dev10101"), (101, 2, "1.1.0.dev10102"), (11, 2, "1.1.0.dev1102")],
)
def test_a_rehearsal_version_is_below_the_release_and_new_for_every_attempt(
    release, number, attempt, expected
):
    assert release.rehearsal_version("1.1.0", number, attempt) == expected


def test_rehearsal_versions_never_collide_across_runs_and_attempts(release):
    seen = {
        release.rehearsal_version("1.1.0", number, attempt)
        for number in range(1, 300)
        for attempt in range(1, 100)
    }
    assert len(seen) == 299 * 99


def test_a_rehearsal_version_sorts_below_the_real_one(release):
    packaging = pytest.importorskip("packaging.version")
    rehearsal = release.rehearsal_version("1.1.0", 5, 1)
    assert packaging.Version(rehearsal) < packaging.Version("1.1.0")
    assert packaging.Version(rehearsal) > packaging.Version("1.0.2")


@pytest.mark.parametrize(("base", "attempt"), [("1.1.0.dev1", 1), ("1.1.0", 0), ("1.1.0", 100)])
def test_a_rehearsal_version_refuses_what_it_cannot_make_unique(release, base, attempt):
    with pytest.raises(release.ReleaseError):
        release.rehearsal_version(base, 5, attempt)


def test_the_version_is_read_and_rewritten_in_place(release, tmp_path):
    source = make_source(tmp_path, version="1.1.0")
    assert release.read_version(source) == "1.1.0"
    release.write_version(source, "1.1.0.dev10101")
    assert release.read_version(source) == "1.1.0.dev10101"
    text = (source / "src" / "conclude" / "__init__.py").read_text(encoding="utf-8")
    assert text == '__version__ = "1.1.0.dev10101"\n'


# --- after the upload --------------------------------------------------------------------


def listing(files):
    return json.dumps(
        {
            "urls": [
                {"filename": name, "digests": {"sha256": digest}} for name, digest in files.items()
            ]
        }
    ).encode()


def local_digests(release, dist):
    return {name: digest for digest, name in release.manifest(dist)}


def test_published_files_maps_names_to_hashes_and_none_means_not_yet(release, monkeypatch):
    answers = iter([(404, b""), (200, listing({"a.whl": "aa", "a.tar.gz": "bb"}))])
    monkeypatch.setattr(release, "fetch", lambda url: next(answers))
    assert release.published_files("https://pypi.org", "1.1.0") is None
    assert release.published_files("https://pypi.org", "1.1.0") == {"a.whl": "aa", "a.tar.gz": "bb"}


def test_an_unexpected_status_from_the_index_is_an_error_not_a_retry(release, monkeypatch):
    monkeypatch.setattr(release, "fetch", lambda url: (503, b""))
    with pytest.raises(release.ReleaseError, match="answered 503"):
        release.published_files("https://pypi.org", "1.1.0")


def test_the_json_url_is_the_versions_own(release, monkeypatch):
    seen = []
    monkeypatch.setattr(release, "fetch", lambda url: (seen.append(url), (404, b""))[1])
    release.published_files("https://test.pypi.org", "1.1.0.dev10101")
    assert seen == ["https://test.pypi.org/pypi/conclude/1.1.0.dev10101/json"]


def test_a_published_file_with_other_bytes_than_were_built_is_refused(
    release, tmp_path, monkeypatch
):
    dist = make_dist(tmp_path)
    remote = {**local_digests(release, dist)}
    wheel = next(name for name in remote if name.endswith(".whl"))
    remote[wheel] = "f" * 64
    monkeypatch.setattr(release, "fetch", lambda url: (200, listing(remote)))
    with pytest.raises(release.ReleaseError, match="is not the file that was built"):
        release.verify_published(
            dist, "https://pypi.org", expect_provenance=False, attempts=3, delay=0
        )


def test_a_file_the_index_does_not_list_yet_is_retried_then_refused(release, tmp_path, monkeypatch):
    dist = make_dist(tmp_path)
    remote = local_digests(release, dist)
    del remote[next(name for name in remote if name.endswith(".tar.gz"))]
    calls = []
    monkeypatch.setattr(
        release, "fetch", lambda url: (calls.append(url), (200, listing(remote)))[1]
    )
    monkeypatch.setattr(release.time, "sleep", lambda seconds: None)
    with pytest.raises(release.ReleaseError, match="still not there after 4 attempts"):
        release.verify_published(
            dist, "https://pypi.org", expect_provenance=False, attempts=4, delay=1
        )
    assert len(calls) == 4


def test_retrying_stops_at_the_first_success_and_waits_between_attempts(release, monkeypatch):
    outcomes = iter(["not yet", "still not", None])
    sleeps = []
    monkeypatch.setattr(release.time, "sleep", sleeps.append)
    release.retrying("thing", lambda: next(outcomes), attempts=5, delay=7)
    assert sleeps == [7, 7]


def test_retrying_does_not_sleep_after_the_last_attempt(release, monkeypatch):
    sleeps = []
    monkeypatch.setattr(release.time, "sleep", sleeps.append)
    with pytest.raises(release.ReleaseError, match="thing: still not there after 2 attempts: nope"):
        release.retrying("thing", lambda: "nope", attempts=2, delay=7)
    assert sleeps == [7]


def test_a_final_error_inside_an_attempt_is_not_retried(release, monkeypatch):
    calls = []

    def attempt():
        calls.append(1)
        raise release.ReleaseError("wrong bytes")

    monkeypatch.setattr(release.time, "sleep", lambda seconds: None)
    with pytest.raises(release.ReleaseError, match="wrong bytes"):
        release.retrying("thing", attempt, attempts=5, delay=0)
    assert len(calls) == 1


# --- the command line --------------------------------------------------------------------


def test_the_command_line_prints_the_fingerprint_and_checks_it(release, tmp_path, capsys):
    dist = make_dist(tmp_path)
    assert release.main(["integrity", str(dist)]) == 0
    digest = capsys.readouterr().out.strip()
    assert digest == release.integrity(dist)
    assert release.main(["check-integrity", str(dist), digest]) == 0


def test_a_failed_check_is_exit_status_1_with_a_github_error_annotation(release, tmp_path, capsys):
    dist = make_dist(tmp_path)
    assert release.main(["check-integrity", str(dist), "sha256-nope"]) == 1
    assert capsys.readouterr().err.startswith("::error::the distributions are not the ones")


def test_rehearsal_version_on_the_command_line_can_write_it(release, tmp_path, capsys):
    source = make_source(tmp_path, version="1.1.0")
    code = release.main(
        [
            f"--source-root={source}",
            "rehearsal-version",
            "--run-number=7",
            "--run-attempt=1",
            "--write",
        ]
    )
    assert code == 0
    assert capsys.readouterr().out.strip() == "1.1.0.dev701"
    assert release.read_version(source) == "1.1.0.dev701"
