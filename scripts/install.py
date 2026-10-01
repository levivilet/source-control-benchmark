"""Download and extract the exact releases in config/editors.lock.json."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "config/editors.lock.json"


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(entry, archive):
    if not archive.exists():
        print(f"Downloading {entry['id']} {entry['version']}", flush=True)
        # The Cursor CDN rejects urllib's default user agent with HTTP 403.
        request = urllib.request.Request(entry["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request) as response, archive.open("wb") as destination:
            shutil.copyfileobj(response, destination)
    actual = checksum(archive)
    if actual != entry["sha256"]:
        raise ValueError(f"Checksum mismatch for {entry['id']}: {actual}")


def extract(entry, archive, destination):
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    if archive.suffix == ".deb":
        subprocess.run(["dpkg-deb", "-x", str(archive), str(destination)], check=True)
    elif archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as source:
            source.extractall(destination)
    else:
        with tarfile.open(archive) as source:
            source.extractall(destination, filter="data")
    binary = destination / entry["binary"]
    if not binary.exists():
        raise FileNotFoundError(f"Binary not found after extracting {entry['id']}: {binary}")
    binary.chmod(binary.stat().st_mode | 0o111)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editors", default=None, help="comma-separated editor ids")
    args = parser.parse_args()
    entries = json.loads(LOCK.read_text())
    by_id = {entry["id"]: entry for entry in entries}
    ids = list(by_id) if args.editors is None else args.editors.split(",")
    if not ids or len(ids) != len(set(ids)) or set(ids) - by_id.keys():
        parser.error("unknown or duplicate editor")
    target = ROOT / ".tmp/apps"
    target.mkdir(parents=True, exist_ok=True)
    for editor_id in ids:
        entry = by_id[editor_id]
        if entry.get("package"):
            print(f"Using runner package {entry['package']}", flush=True)
            continue
        archive = target / entry["archive"]
        download(entry, archive)
        extract(entry, archive, target / editor_id)
        print(f"Verified {editor_id} {entry['sha256']}", flush=True)


if __name__ == "__main__":
    main()
