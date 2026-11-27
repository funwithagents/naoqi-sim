"""Fetch what the NAOqi images are built from into the image data folder's <version>/ (`files.IMAGE_DATA`:
docker/image-data/ in a checkout, the user data directory when installed): the pinned Choregraphe
suite, the robot's `animations` package extracted from the public robot image (on 2.8 also a NAO's
Autonomous Life configuration, from the image's `life` package, and two of the robot's own services,
`altactilegesture` and `signs-and-feedback`), and the build files
whose headers our C++ NAOqi modules are compiled against (the version's own C++ SDK:
specs/container/container.md, "Build files").

These are Aldebaran's files, downloaded from Aldebaran's own public sources (its GitHub
repositories with Git LFS; its download site for the 2.1 SDK, which no repository holds) to this
machine only: they stay in the image data folder (gitignored in a checkout, never in the wheel)
and in locally built images, never in the repository or a pushed image.

A file already there with the pinned hash is kept, so the command is cheap to re-run. A file with
the expected name but another hash (a Git LFS pointer, a truncated copy) is an error and is left
alone. Downloads and extractions go to `<file>.part`, are hashed on the fly and only take the
final name once the hash matches. Each verified file's size, modification time and hash are
recorded in `<image-data>/hashes.json`, so a file that has not changed since is not hashed again
(the 2.8 suite alone is 1.3 GB).

`check_image_data` asks each pinned URL, with a HEAD request and no download, whether it still
serves the pinned file: what CI runs every night (specs/testing/ci.md, "The nightly image data check").

The robot image (`.opn`) is a 4096-byte `ALDIMAGE` header, an installer shell script whose
variables locate the payload, then the compressed ext3 root filesystem (bzip2 on 2.1, gzip on
2.8). It is decompressed here and streamed into a throwaway Alpine container, whose `debugfs`
writes the package to stdout: no ext3 tooling or mount is needed on the host. A robot package is a
zip archive, from which a single file is read in memory.
"""

import bz2
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from naoqi_sim import files
from naoqi_sim.errors import FetchError

IMAGE_DATA = files.IMAGE_DATA
CHUNK = 1 << 20
PACKAGE = "animations.pkg"
LIFE_CONFIG = "autonomy.cfg"  # the robot's Life configuration, as Life reads it from ~/.config/naoqi/

# Git LFS files are served from media.githubusercontent.com; the raw URL returns the pointer.
_V5 = "https://media.githubusercontent.com/media/aldebaran/NAO-V5-ressources/main/"
_V6 = "https://media.githubusercontent.com/media/aldebaran/nao6-binaries/master/"
_V6_SDK = "https://media.githubusercontent.com/media/aldebaran/nao6-doc-sdk/master/"
_SDK = "https://community-static.aldebaran.com/resources/"  # 2.1's SDK: on no GitHub repository


@dataclass(frozen=True)
class PinnedFile:
    url: str
    sha256: str
    name: str | None = None  # saved under this name instead of the URL's last part
    size: int | None = (
        None  # in bytes: what the image data check expects as Content-Length
    )

    @property
    def filename(self) -> str:
        return self.name or urllib.parse.unquote(self.url.rsplit("/", 1)[1])


@dataclass(frozen=True)
class PackagedFile:
    """A file inside a package of the robot image: the package's path in the root filesystem and
    its hash, the file's path in the package and its hash."""

    package_path: str
    package_sha256: str
    member: str
    sha256: str


@dataclass(frozen=True)
class RobotPackage:
    """A package of the robot image taken whole, as `animations.pkg` is: its path in the root
    filesystem, its hash, and the plain name it is saved and copied into the image under."""

    path: str
    sha256: str
    name: str


@dataclass(frozen=True)
class Version:
    name: str
    suite: PinnedFile
    image: PinnedFile  # the robot system image the package is extracted from
    package_path: str  # animations.pkg inside the image's root filesystem
    package_sha256: str
    # Headers the native relay is compiled against in the image build (Dockerfile stage `relay`)
    build_files: tuple[PinnedFile, ...] = ()
    # A NAO's Life configuration, from the robot's `life` package (2.8: the desktop suite's has no
    # rule taking Life to a person; specs/container/autonomous-life.md)
    life_config: PackagedFile | None = None
    # More of the robot's packages, installed at boot beside `animations` (2.8: its tactile
    # gestures and its signs and feedback; specs/container/container.md, "Robot packages in the image")
    packages: tuple[RobotPackage, ...] = ()


VERSIONS = {
    "2.1": Version(
        "2.1",
        PinnedFile(
            _V5
            + "Choregraphe/Linux/Binaries/choregraphe-suite-2.1.4.13-linux64.tar.gz",
            "bad0212956e2223f36736cff33bdc1e008311b8bf9efd81a52dcf05895c8abce",
            size=430_850_260,
        ),
        PinnedFile(
            _V5
            + "NAOqi%202.1.4.13/NAOqi%20Images/opennao-atom-system-image-2.1.4.13_2015-08-27.opn",
            "5d18427ba6f5199d30cf29941b20ad5fa6a06b8f64a29126953cdfa33dbb9a24",
            size=376_985_600,
        ),
        "/usr/share/naoqi/apps/animations.pkg",  # version 5.0.9
        "a1d46221f5f28b91c8e7564ade4532f390e5911f14210787b3352a84c2b507e1",
        (
            PinnedFile(
                _SDK + "2.1.4.13/sdk-c%2B%2B/naoqi-sdk-2.1.4.13-linux64.tar.gz",
                "a1669524819088b7aac82e04450e2c5dce6ffdd11c968444db89b6831955683b",
                size=333_867_205,
            ),
        ),
    ),
    "2.8": Version(
        "2.8",
        PinnedFile(
            _V6 + "choregraphe-suite-2.8.7.4-linux64.tar.gz",
            "edf95da2ae8ec7573e3a590b6db47a472f9d2733280a4a597841fbf0c1e6c63c",
            size=1_330_448_842,
        ),
        PinnedFile(
            _V6 + "nao-x86-2.8.7.4_20210820_094013.opn",
            "d82e5dd221712555f20c430f3ebcbe46825d5179f1bc0e2594629489855e24a4",
            size=731_909_120,
        ),
        "/opt/aldebaran/share/naoqi/apps/animations.pkg",  # version 7.0.3
        "8866ddf4bb45eab79068cfe5746c66f3b8f507356fd93affed204bc834002f2c",
        (
            # The suite's own release: module API, libqi and boost 1.64 headers.
            PinnedFile(
                _V6_SDK + "naoqi-sdk-2.8.7.4-linux64.tar.gz",
                "e42c8b95e6e3de349cf76100d006a9f5b48bd625f0236b0a0fe094fc29970967",
                size=1_345_290_750,
            ),
        ),
        PackagedFile(
            "/opt/aldebaran/share/naoqi/apps/life-0.0.13-agility-274-atom.pkg",
            "5502364f8787498c9084205be6141f69c394dd58af7e89f4bbfe7b4b98977859",
            "etc/naoqi/autonomy-nao-romeo.cfg",
            "587dfce272003c01e21c045f6c143b52dcd9e5f56e0df32ed2c171fa2c9a5917",
        ),
        (
            RobotPackage(
                "/opt/aldebaran/share/naoqi/apps/altactilegesture-1.0.0.pkg",
                "e3fde7b3f27f5aca090e13036ca79f4a3a5ab2c0c7e84beb220136ef028e3b4a",
                "altactilegesture.pkg",
            ),
            RobotPackage(
                "/opt/aldebaran/share/naoqi/apps/signs-and-feedback-0.3.11-.pkg",
                "e6c1bdf3d5363ee073f2251130d278b6d866a6213e05af86aefcf7d526213b48",
                "signs-and-feedback.pkg",
            ),
        ),
    ),
}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


HASHES = "hashes.json"  # in the image data folder


def _record_path(path: Path) -> tuple[Path, str]:
    """The image data folder's hash record and the file's key in it (`<version>/<name>`)."""
    return path.parent.parent / HASHES, f"{path.parent.name}/{path.name}"


def _load_record(record: Path) -> dict[str, dict]:
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # absent or unreadable: hash everything again
        return {}
    return data if isinstance(data, dict) else {}


def _stamp(path: Path) -> dict:
    st = path.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def _remember(path: Path, sha256: str) -> None:
    """Record that `path`, as it is now, has hash `sha256`."""
    record, key = _record_path(path)
    entries = _load_record(record)
    entries[key] = {**_stamp(path), "sha256": sha256}
    record.write_text(
        json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _unchanged(path: Path, sha256: str) -> bool:
    """True if `path` was verified with hash `sha256` and its size and time have not changed."""
    record, key = _record_path(path)
    return _load_record(record).get(key) == {**_stamp(path), "sha256": sha256}


def _present(path: Path, sha256: str) -> bool:
    """True if `path` holds the pinned file, False if absent; any other file is an error."""
    if not path.exists():
        return False
    if _unchanged(path, sha256):
        _log(f"{path.name}: already present (unchanged since verified)")
        return True
    if _sha256(path) != sha256:
        raise FetchError(
            f"{path} is not the pinned file (SHA-256 mismatch; a Git LFS pointer or a "
            "partial copy?). Delete it to fetch it again."
        )
    _remember(path, sha256)
    _log(f"{path.name}: already present")
    return True


def _write(chunks: Iterable[bytes], dest: Path, sha256: str, source: str) -> None:
    """Write `chunks` to `<dest>.part`, then rename it to `dest` if its hash is `sha256`."""
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    try:
        with part.open("wb") as f:
            for chunk in chunks:
                f.write(chunk)
                h.update(chunk)
        if h.hexdigest() != sha256:
            raise FetchError(
                f"{source}: got SHA-256 {h.hexdigest()}, expected {sha256}"
            )
        part.rename(dest)
    finally:
        part.unlink(missing_ok=True)
    _remember(dest, sha256)
    _log(f"{dest} verified")


def _download(url: str) -> Iterator[bytes]:
    with urllib.request.urlopen(url) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done, shown = 0, -1
        while chunk := r.read(CHUNK):
            yield chunk
            done += len(chunk)
            if total and (pct := done * 100 // total) // 10 != shown:
                shown = pct // 10
                _log(f"  {pct}% of {total // 1_000_000} MB")


def fetch_file(f: PinnedFile, folder: Path) -> Path:
    """Make sure `folder` holds the pinned file; download it if absent. Returns its path."""
    dest = folder / f.filename
    if not _present(dest, f.sha256):
        folder.mkdir(parents=True, exist_ok=True)
        _log(f"downloading {f.url}")
        _write(_download(f.url), dest, f.sha256, f.url)
    return dest


def download_problem(f: PinnedFile, timeout: float = 30.0) -> str | None:
    """Why `f`'s URL does not serve the pinned file, or None when it does. A HEAD request:
    nothing is downloaded. The answer must be a 200 with the pinned size, when one is pinned;
    and GitHub's LFS storage gives a file's SHA-256 as its ETag, which must then be the pinned
    one (another server's ETag, which is not a SHA-256, says nothing)."""
    request = urllib.request.Request(f.url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            headers = r.headers
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {e.reason}"
    except OSError as e:  # no route, no name, a timeout, a refused connection
        return f"no answer ({e})"
    length = headers.get("Content-Length")
    if f.size is not None and length != str(f.size):
        return f"Content-Length is {length}, expected {f.size}"
    etag = (headers.get("ETag") or "").removeprefix("W/").strip('"').lower()
    if re.fullmatch(r"[0-9a-f]{64}", etag) and etag != f.sha256:
        return f"the server's SHA-256 is {etag}, expected {f.sha256}"
    return None


def check_image_data(
    versions: Iterable[Version] | None = None,
    attempts: int = 3,
    pause: float = 10.0,
    timeout: float = 30.0,
) -> list[str]:
    """Ask every pinned URL of `versions` (all of them by default) whether it still serves its
    file: the suite, the robot image and the build files. Returns one line per file that does
    not, after `attempts` tries `pause` seconds apart, so a passing network fault is not a
    missing file. Empty when every download is there."""
    problems = []
    for version in VERSIONS.values() if versions is None else versions:
        for f in (version.suite, version.image, *version.build_files):
            problem = download_problem(f, timeout)
            for _ in range(attempts - 1):
                if problem is None:
                    break
                time.sleep(pause)
                problem = download_problem(f, timeout)
            if problem is None:
                _log(f"available: {f.url}")
            else:
                _log(f"UNAVAILABLE: {f.url}: {problem}")
                problems.append(f"NAOqi {version.name}: {f.url}: {problem}")
    return problems


@dataclass(frozen=True)
class OpnPayload:
    offset: int
    length: int
    compression: str  # "bzip2" or "gzip"


_MAGIC = {"bzip2": b"BZh", "gzip": b"\x1f\x8b"}


def opn_payload(opn: Path) -> OpnPayload:
    """Where a robot image's compressed root filesystem is, from its installer's variables."""
    with opn.open("rb") as f:
        head = f.read(4096 + 128 * 1024)
        if not head.startswith(b"ALDIMAGE"):
            raise FetchError(f"{opn} is not a NAO robot image (no ALDIMAGE header)")
        found = dict(
            re.findall(
                rb'^(MAGIC_SIZE|SIZE_BASE|INSTALLER_SIZE|IMAGE_CMP_SIZE)="?(\d+)"?\s*$',
                head,
                re.MULTILINE,
            )
        )
        try:
            magic, base, installer, size = (
                int(found[k])
                for k in (
                    b"MAGIC_SIZE",
                    b"SIZE_BASE",
                    b"INSTALLER_SIZE",
                    b"IMAGE_CMP_SIZE",
                )
            )
        except KeyError as e:
            raise FetchError(
                f"{opn}: installer variable {e.args[0].decode()} not found"
            ) from None
        offset = magic + installer * base
        f.seek(offset)
        start = f.read(3)
    for compression, m in _MAGIC.items():
        if start.startswith(m):
            return OpnPayload(offset, size * base, compression)
    raise FetchError(f"{opn}: unknown compression at byte {offset} ({start.hex()})")


def rootfs_chunks(opn: Path) -> Iterator[bytes]:
    """The robot image's root filesystem, decompressed (concatenated streams included)."""
    p = opn_payload(opn)
    magic = _MAGIC[p.compression]

    def new():
        return (
            bz2.BZ2Decompressor()
            if p.compression == "bzip2"
            else zlib.decompressobj(31)
        )

    d = None
    pending = b""
    with opn.open("rb") as f:
        f.seek(p.offset)
        left = p.length
        while left > 0 and (data := f.read(min(CHUNK, left))):
            left -= len(data)
            data = pending + data
            pending = b""
            while data:
                if (
                    d is None
                ):  # between streams: another one, or the padding after the last
                    if len(data) < len(magic):
                        pending = data
                        break
                    if not data.startswith(magic):
                        return
                    d = new()
                if out := d.decompress(data):
                    yield out
                if not d.eof:
                    break
                data = d.unused_data
                d = None
    if d is not None:
        raise FetchError(f"{opn}: the compressed root filesystem is truncated")


# Runs in alpine: store the filesystem streamed on stdin, then print one file of it ($0).
_DEBUGFS = 'apk add --no-cache -q e2fsprogs-extra >&2 && cat > /rootfs && debugfs -R "cat $0" /rootfs'


def docker_cat(rootfs: Iterable[bytes], path: str) -> Iterator[bytes]:
    """The file at `path` in the ext3 filesystem `rootfs`, read by debugfs in a throwaway container."""
    docker = (
        shutil.which("docker") or "docker"
    )  # on Windows, as a shell finds it (PATHEXT)
    proc = subprocess.Popen(
        [docker, "run", "-i", "--rm", "alpine:3.20", "sh", "-c", _DEBUGFS, path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None
    stdin, stdout = proc.stdin, proc.stdout
    failed: list[Exception] = []

    def feed():
        try:
            for chunk in rootfs:
                stdin.write(chunk)
        except BrokenPipeError:
            pass
        except (FetchError, OSError, zlib.error) as e:  # bad payload: re-raised below
            failed.append(e)
            proc.kill()
        finally:
            stdin.close()

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    yield from iter(lambda: stdout.read(CHUNK), b"")
    feeder.join()
    if failed:
        raise failed[0]
    if proc.wait() != 0:
        raise FetchError(
            f"extracting {path} with docker failed (exit {proc.returncode})"
        )


Cat = Callable[[Iterable[bytes], str], Iterable[bytes]]


def _packaged(chunks: Iterable[bytes], f: PackagedFile, source: str) -> bytes:
    """The file `f` names, out of its package's bytes `chunks`, both hashes checked."""
    package = b"".join(chunks)
    got = hashlib.sha256(package).hexdigest()
    if got != f.package_sha256:
        raise FetchError(f"{source}: got SHA-256 {got}, expected {f.package_sha256}")
    try:
        return zipfile.ZipFile(io.BytesIO(package)).read(f.member)
    except (zipfile.BadZipFile, KeyError) as e:
        raise FetchError(f"{source}: no {f.member} in the package ({e})") from e


def fetch(
    version: Version, image_data: Path = IMAGE_DATA, cat: Cat = docker_cat
) -> Path:
    """Make sure `<image-data>/<version>/` holds the suite, `animations.pkg`, the Life
    configuration and the robot's other packages (2.8), and the build files. Returns the folder."""
    folder = image_data / version.name
    _log(f"NAOqi {version.name}")
    fetch_file(version.suite, folder)
    for f in version.build_files:
        fetch_file(f, folder)
    package = folder / PACKAGE
    life = version.life_config
    need_package = not _present(package, version.package_sha256)
    need_life = life is not None and not _present(folder / LIFE_CONFIG, life.sha256)
    missing = [p for p in version.packages if not _present(folder / p.name, p.sha256)]
    if need_package or need_life or missing:
        opn = folder / version.image.filename
        users = opn.exists()  # a robot image the user put there is kept
        try:
            fetch_file(version.image, folder)
            if need_package:
                _log(
                    f"extracting {version.package_path} from {opn.name} (needs Docker)"
                )
                _write(
                    cat(rootfs_chunks(opn), version.package_path),
                    package,
                    version.package_sha256,
                    f"{opn.name}:{version.package_path}",
                )
            if life is not None and need_life:
                source = f"{opn.name}:{life.package_path}"
                _log(f"extracting {life.member} from {source} (needs Docker)")
                config = _packaged(
                    cat(rootfs_chunks(opn), life.package_path), life, source
                )
                _write(
                    [config],
                    folder / LIFE_CONFIG,
                    life.sha256,
                    f"{source}:{life.member}",
                )
            for p in missing:
                _log(f"extracting {p.path} from {opn.name} (needs Docker)")
                _write(
                    cat(rootfs_chunks(opn), p.path),
                    folder / p.name,
                    p.sha256,
                    f"{opn.name}:{p.path}",
                )
        finally:
            if not users:
                opn.unlink(missing_ok=True)
    return folder
