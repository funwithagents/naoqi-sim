import bz2
import gzip
import hashlib
import io
import json
import re
import threading
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from naoqi_sim import suite
from naoqi_sim.errors import FetchError
from naoqi_sim.suite import (
    LIFE_CONFIG,
    PACKAGE,
    VERSIONS,
    PackagedFile,
    PinnedFile,
    RobotPackage,
    Version,
    fetch,
    opn_payload,
    rootfs_chunks,
)

DOCKER = Path(__file__).resolve().parent.parent / "docker"
SUITE = b"not really a suite\n" * 100_000  # ~1.9 MB: several chunks
ROOTFS = bytes(range(256)) * 12_000  # ~3 MB: several chunks, compressed and not
BASE = 1024


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def make_opn(
    payload: bytes,
    compress: Callable[[bytes], bytes],
    installer_kb: int = 4,
    trailing: bytes = b"\0" * 5000,
) -> bytes:
    """A robot image laid out like Aldebaran's: header, installer script, compressed payload."""
    data = compress(payload)
    cmp_kb = -(-len(data) // BASE)
    script = (
        "#!/bin/sh\n# Set at image creation time\n"
        f'SIZE_BASE="{BASE}"\nIMAGE_CMP_SIZE="{cmp_kb}"\n'
        f'INSTALLER_SIZE="{installer_kb}"\nMAGIC_SIZE=4096\n'
    ).encode()
    return (
        b"ALDIMAGE".ljust(4096, b"\0")
        + script.ljust(installer_kb * BASE, b"\0")
        + data.ljust(cmp_kb * BASE, b"\0")
        + trailing
    )


def two_bzip2_streams(b: bytes) -> bytes:
    return bz2.compress(b[:1000]) + bz2.compress(b[1000:])


def two_gzip_members(b: bytes) -> bytes:
    return gzip.compress(b[:1000]) + gzip.compress(b[1000:])


@pytest.mark.parametrize(
    ("compress", "compression"),
    [
        (bz2.compress, "bzip2"),
        (gzip.compress, "gzip"),
        (two_bzip2_streams, "bzip2"),
        (two_gzip_members, "gzip"),
    ],
)
def test_reads_the_root_filesystem_out_of_a_robot_image(
    tmp_path, compress, compression
):
    opn = tmp_path / "nao.opn"
    opn.write_bytes(make_opn(ROOTFS, compress, installer_kb=7))
    payload = opn_payload(opn)
    assert payload.offset == 4096 + 7 * BASE
    assert payload.compression == compression
    assert b"".join(rootfs_chunks(opn)) == ROOTFS


def test_rejects_what_is_not_a_robot_image(tmp_path):
    opn = tmp_path / "nao.opn"
    opn.write_bytes(b"version https://git-lfs.github.com/spec/v1\n")
    with pytest.raises(FetchError, match="ALDIMAGE"):
        opn_payload(opn)


def test_rejects_a_truncated_robot_image(tmp_path):
    opn = tmp_path / "nao.opn"
    whole = make_opn(ROOTFS, bz2.compress, trailing=b"")
    opn.write_bytes(whole[: len(whole) // 2])
    with pytest.raises(FetchError, match="truncated"):
        b"".join(rootfs_chunks(opn))


class Origin:
    """A local stand-in for media.githubusercontent.com, counting requests per path."""

    def __init__(self, files: dict[str, bytes]):
        origin = self
        self.files = files
        self.requests: list[str] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                origin.requests.append(self.path)
                body = origin.files[self.path]
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def echo_cat(rootfs: Iterable[bytes], path: str) -> Iterable[bytes]:
    """Stands in for debugfs in Docker: the synthetic root filesystem *is* the package."""
    return rootfs


PKG = ROOTFS  # what echo_cat yields for a robot image made from ROOTFS
OPN = make_opn(ROOTFS, bz2.compress)
SDK = b"an sdk\n" * 1000
LIBQI = b"libqi sources\n" * 1000


@pytest.fixture
def origin():
    o = Origin(
        {
            "/suite.tar.gz": SUITE,
            "/nao%20image.opn": OPN,
            "/sdk.tar.gz": SDK,
            "/archive/abc123.tar.gz": LIBQI,
        }
    )
    yield o
    o.close()


def version(
    origin: Origin, package_sha256: str = sha(PKG), suite_body: bytes = SUITE
) -> Version:
    return Version(
        "2.1",
        PinnedFile(f"{origin.base}/suite.tar.gz", sha(suite_body)),
        PinnedFile(f"{origin.base}/nao%20image.opn", sha(OPN)),
        "/usr/share/naoqi/apps/animations.pkg",
        package_sha256,
    )


def with_build_files(origin: Origin, sdk_body: bytes = SDK) -> Version:
    return replace(
        version(origin),
        build_files=(
            PinnedFile(f"{origin.base}/sdk.tar.gz", sha(sdk_body)),
            PinnedFile(
                f"{origin.base}/archive/abc123.tar.gz",
                sha(LIBQI),
                "libqi-abc123.tar.gz",
            ),
        ),
    )


def test_fetches_the_build_files_under_their_pinned_names(origin, tmp_path):
    folder = fetch(with_build_files(origin), tmp_path, echo_cat)
    assert (folder / "sdk.tar.gz").read_bytes() == SDK
    assert (folder / "libqi-abc123.tar.gz").read_bytes() == LIBQI
    assert sorted(p.name for p in folder.iterdir()) == [
        PACKAGE,
        "libqi-abc123.tar.gz",
        "sdk.tar.gz",
        "suite.tar.gz",
    ]

    fetch(with_build_files(origin), tmp_path, echo_cat)
    assert sorted(origin.requests) == sorted(
        ["/suite.tar.gz", "/nao%20image.opn", "/sdk.tar.gz", "/archive/abc123.tar.gz"]
    )  # each once: a second fetch keeps them


def test_rejects_a_build_file_with_the_wrong_hash(origin, tmp_path):
    with pytest.raises(FetchError, match="sdk.tar.gz.*SHA-256"):
        fetch(with_build_files(origin, sdk_body=b"another sdk"), tmp_path, echo_cat)
    assert not (tmp_path / "2.1" / "sdk.tar.gz").exists()


def test_fills_the_version_folder(origin, tmp_path):
    folder = fetch(version(origin), tmp_path, echo_cat)
    assert folder == tmp_path / "2.1"
    assert (folder / "suite.tar.gz").read_bytes() == SUITE
    assert (folder / PACKAGE).read_bytes() == PKG
    # The robot image it downloaded only to extract the package is gone, and nothing half-done is left.
    assert sorted(p.name for p in folder.iterdir()) == [PACKAGE, "suite.tar.gz"]


def test_downloads_nothing_when_everything_is_there(origin, tmp_path):
    fetch(version(origin), tmp_path, echo_cat)
    fetch(version(origin), tmp_path, echo_cat)
    assert len(origin.requests) == 2  # the suite and the robot image, once each


def test_unchanged_files_are_not_hashed_again(origin, tmp_path, monkeypatch):
    fetch(version(origin), tmp_path, echo_cat)
    hashed: list[Path] = []
    real = suite._sha256
    monkeypatch.setattr(suite, "_sha256", lambda p: hashed.append(p) or real(p))

    fetch(version(origin), tmp_path, echo_cat)
    assert hashed == []
    assert len(origin.requests) == 2  # and nothing was downloaded again


def test_a_file_changed_since_its_verification_is_hashed_again(origin, tmp_path):
    fetch(version(origin), tmp_path, echo_cat)
    suite_file = tmp_path / "2.1" / "suite.tar.gz"
    suite_file.write_bytes(b"truncated")  # another size and time than recorded

    with pytest.raises(FetchError, match="Delete it"):
        fetch(version(origin), tmp_path, echo_cat)


def test_a_lost_hash_record_only_costs_a_rehash(origin, tmp_path):
    fetch(version(origin), tmp_path, echo_cat)
    (tmp_path / suite.HASHES).write_text("not json")

    fetch(version(origin), tmp_path, echo_cat)
    assert len(origin.requests) == 2
    assert json.loads((tmp_path / suite.HASHES).read_text())["2.1/suite.tar.gz"][
        "sha256"
    ] == sha(SUITE)


def test_uses_and_keeps_a_robot_image_the_user_put_there(origin, tmp_path):
    (tmp_path / "2.1").mkdir()
    (tmp_path / "2.1" / "nao image.opn").write_bytes(OPN)
    fetch(version(origin), tmp_path, echo_cat)
    assert origin.requests == ["/suite.tar.gz"]
    assert (tmp_path / "2.1" / "nao image.opn").exists()
    assert (tmp_path / "2.1" / PACKAGE).read_bytes() == PKG


def test_rejects_an_extracted_package_with_the_wrong_hash(origin, tmp_path):
    with pytest.raises(FetchError, match="SHA-256"):
        fetch(
            version(origin, package_sha256=sha(b"another package")), tmp_path, echo_cat
        )
    assert sorted(p.name for p in (tmp_path / "2.1").iterdir()) == ["suite.tar.gz"]


CONFIG = b"[Interactive]\nCondition: 'Launchpad/NumPeopleZone1' > 0\n"
LIFE_MEMBER = "etc/naoqi/autonomy-nao-romeo.cfg"


def zipped(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


LIFE_PKG = zipped({"manifest.xml": b"<package/>", LIFE_MEMBER: CONFIG})


class PathCat:
    """Stands in for debugfs in Docker, answering by path; records what was read."""

    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.read: list[str] = []

    def __call__(self, rootfs: Iterable[bytes], path: str) -> Iterable[bytes]:
        self.read.append(path)
        return [self.files[path]]


def with_life(origin: Origin, member: str = LIFE_MEMBER, package: bytes = LIFE_PKG):
    return replace(
        version(origin),
        life_config=PackagedFile("/apps/life.pkg", sha(package), member, sha(CONFIG)),
    )


def robot_files(package: bytes = LIFE_PKG) -> PathCat:
    return PathCat(
        {"/usr/share/naoqi/apps/animations.pkg": PKG, "/apps/life.pkg": package}
    )


def test_extracts_a_naos_life_configuration_from_the_robot_images_life_package(
    origin, tmp_path
):
    cat = robot_files()
    folder = fetch(with_life(origin), tmp_path, cat)
    assert (folder / LIFE_CONFIG).read_bytes() == CONFIG
    assert (folder / PACKAGE).read_bytes() == PKG
    assert sorted(p.name for p in folder.iterdir()) == [
        PACKAGE,
        LIFE_CONFIG,
        "suite.tar.gz",
    ]
    assert origin.requests.count("/nao%20image.opn") == 1  # one download for both files
    fetch(with_life(origin), tmp_path, cat)
    assert len(origin.requests) == 2 and len(cat.read) == 2  # kept, nothing read again


def test_only_the_missing_file_is_extracted_again(origin, tmp_path):
    cat = robot_files()
    fetch(with_life(origin), tmp_path, cat)
    (tmp_path / "2.1" / LIFE_CONFIG).unlink()
    fetch(with_life(origin), tmp_path, cat)
    assert cat.read == [
        "/usr/share/naoqi/apps/animations.pkg",
        "/apps/life.pkg",
        "/apps/life.pkg",
    ]
    assert (tmp_path / "2.1" / LIFE_CONFIG).read_bytes() == CONFIG


def test_rejects_a_life_package_with_the_wrong_hash(origin, tmp_path):
    other = zipped({LIFE_MEMBER: CONFIG, "more": b"another release"})
    with pytest.raises(FetchError, match="life.pkg.*SHA-256"):
        fetch(with_life(origin), tmp_path, robot_files(package=other))
    assert not (tmp_path / "2.1" / LIFE_CONFIG).exists()


def test_rejects_a_life_package_without_the_configuration(origin, tmp_path):
    with pytest.raises(FetchError, match="no etc/naoqi/missing.cfg"):
        fetch(
            with_life(origin, member="etc/naoqi/missing.cfg"), tmp_path, robot_files()
        )
    assert not (tmp_path / "2.1" / LIFE_CONFIG).exists()


GESTURES_PKG = zipped({"manifest.xml": b"<package uuid='altactilegesture'/>"})
FEEDBACK_PKG = zipped({"manifest.xml": b"<package uuid='signs-and-feedback'/>"})


def with_packages(origin: Origin, feedback: bytes = FEEDBACK_PKG) -> Version:
    return replace(
        version(origin),
        packages=(
            RobotPackage("/apps/gestures-1.0.pkg", sha(GESTURES_PKG), "gestures.pkg"),
            RobotPackage("/apps/feedback-0.3-.pkg", sha(feedback), "feedback.pkg"),
        ),
    )


def robot_packages() -> PathCat:
    return PathCat(
        {
            "/usr/share/naoqi/apps/animations.pkg": PKG,
            "/apps/gestures-1.0.pkg": GESTURES_PKG,
            "/apps/feedback-0.3-.pkg": FEEDBACK_PKG,
        }
    )


def test_takes_the_robots_other_packages_whole_under_plain_names(origin, tmp_path):
    cat = robot_packages()
    folder = fetch(with_packages(origin), tmp_path, cat)
    assert (folder / "gestures.pkg").read_bytes() == GESTURES_PKG
    assert (folder / "feedback.pkg").read_bytes() == FEEDBACK_PKG
    assert sorted(p.name for p in folder.iterdir()) == [
        PACKAGE,
        "feedback.pkg",
        "gestures.pkg",
        "suite.tar.gz",
    ]
    assert origin.requests.count("/nao%20image.opn") == 1  # one download for every file
    fetch(with_packages(origin), tmp_path, cat)
    assert len(origin.requests) == 2 and len(cat.read) == 3  # kept, nothing read again


def test_a_folder_filled_before_the_packages_existed_gets_them(origin, tmp_path):
    fetch(
        version(origin), tmp_path, robot_packages()
    )  # what an earlier naoqi-sim pinned
    cat = robot_packages()
    fetch(with_packages(origin), tmp_path, cat)
    # The robot image is downloaded again, and only the packages are read out of it.
    assert origin.requests.count("/nao%20image.opn") == 2
    assert cat.read == ["/apps/gestures-1.0.pkg", "/apps/feedback-0.3-.pkg"]
    assert not (tmp_path / "2.1" / "nao image.opn").exists()


def test_rejects_a_robot_package_with_the_wrong_hash(origin, tmp_path):
    with pytest.raises(FetchError, match="feedback-0.3-.pkg.*SHA-256"):
        fetch(
            with_packages(origin, feedback=b"another release"),
            tmp_path,
            robot_packages(),
        )
    assert not (tmp_path / "2.1" / "feedback.pkg").exists()
    assert (tmp_path / "2.1" / "gestures.pkg").read_bytes() == GESTURES_PKG


def test_rejects_a_download_with_the_wrong_hash(origin, tmp_path):
    with pytest.raises(FetchError, match="SHA-256"):
        fetch(version(origin, suite_body=b"something else"), tmp_path, echo_cat)
    assert list((tmp_path / "2.1").iterdir()) == []


def test_leaves_a_mismatching_local_file_alone(origin, tmp_path):
    lfs_pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:...\n"
    (tmp_path / "2.1").mkdir()
    (tmp_path / "2.1" / "suite.tar.gz").write_bytes(lfs_pointer)
    with pytest.raises(FetchError, match="Delete it"):
        fetch(version(origin), tmp_path, echo_cat)
    assert (tmp_path / "2.1" / "suite.tar.gz").read_bytes() == lfs_pointer
    assert origin.requests == []


@pytest.mark.parametrize("name", ["2.1", "2.8"])
def test_the_dockerfile_builds_from_the_fetched_files(name):
    v = VERSIONS[name]
    dockerfile = (DOCKER / "naoqi" / f"Dockerfile.naoqi-{name}").read_text()
    assert re.search(
        rf"^ARG SUITE={re.escape(v.suite.filename)}$", dockerfile, re.MULTILINE
    )
    # Both files come from the `image-data` build context, which compose points at the version's
    # folder of the image data folder fetch() fills.
    assert "COPY --from=image-data ${SUITE} " in dockerfile
    assert (
        f"COPY --from=image-data {PACKAGE} /opt/naoqi/share/naoqi/apps/{PACKAGE}"
        in dockerfile
    )
    # 2.8's Life reads a NAO's configuration where Life looks first (autonomous-life.md).
    life = f"COPY --from=image-data --chown=1000:1000 {LIFE_CONFIG} /home/nao/.config/naoqi/{LIFE_CONFIG}"
    assert (life in dockerfile) == (v.life_config is not None) == (name == "2.8")
    # 2.8's other robot packages, installed at boot beside animations (container.md).
    assert bool(v.packages) == (name == "2.8")
    for p in v.packages:
        assert p.path.startswith("/opt/aldebaran/share/naoqi/apps/")
        assert re.fullmatch(r"[0-9a-f]{64}", p.sha256)
        assert re.search(
            rf"^COPY --from=image-data .*\b{re.escape(p.name)}\b.* /opt/naoqi/share/naoqi/apps/$",
            dockerfile,
            re.MULTILINE,
        ), p.name
    compose = (DOCKER / "compose.yaml").read_text()
    assert f"image-data: ${{NAOQI_SIM_IMAGE_DATA:-./image-data}}/{name}\n" in compose
    for f in (v.suite, v.image):
        assert f.url.startswith("https://media.githubusercontent.com/media/aldebaran/")
        assert re.fullmatch(r"[0-9a-f]{64}", f.sha256)
    # The relay's build files come from the same context, each by its pinned name.
    assert v.build_files
    for f in v.build_files:
        assert f.url.startswith("https://") and re.fullmatch(r"[0-9a-f]{64}", f.sha256)
        arg = re.search(
            rf"^ARG (\w+)={re.escape(f.filename)}$", dockerfile, re.MULTILINE
        )
        assert arg, f.filename
        assert f"COPY --from=image-data ${{{arg.group(1)}}} " in dockerfile
