"""Pinned public acquisition and bounded extraction for local model setup.

MIT License. Copyright (c) 2026 Blackheart909.
Never follows links from archives or overwrites an existing destination.
"""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import ssl
import stat
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

INITIAL_HOSTS = {'github.com', 'raw.githubusercontent.com', 'files.pythonhosted.org'}
GITHUB_REDIRECTS = {'github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'}


def extractor_available():
    """Fail before downloading if the frozen host omits TAR/gzip support."""
    try:
        import io
        import tarfile
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz'):
            pass
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode='r:gz') as archive:
            if archive.getmembers():
                raise ValueError('Unexpected TAR capability probe contents')
    except Exception as error:
        # This tiny in-memory check catches missing compression modules too.
        raise ValueError('This Decky Python build lacks required TAR/gzip support; existing model management remains available') from error


def safe_path(path):
    p = Path(os.path.abspath(os.fspath(path)))
    for current in (p, *p.parents):
        if current.is_symlink():
            raise ValueError('Setup paths cannot contain symbolic links')
        if current.exists():
            info = current.stat()
            if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
                raise ValueError('Setup paths must be regular files or directories')
            if stat.S_ISREG(info.st_mode) and (current != p or info.st_nlink != 1):
                raise ValueError('Setup files cannot be linked or used as directories')
    return p


def _url(url, hosts, signed=False):
    if not isinstance(url, str) or any(ord(c) <= 32 for c in url) or '\\' in url:
        raise ValueError('Invalid public download URL')
    p = urllib.parse.urlsplit(url)
    if (p.scheme != 'https' or p.hostname not in hosts or p.username or p.password
            or p.port is not None or p.fragment or (p.query and not signed)):
        raise ValueError('Untrusted public download URL')
    return p.hostname


class _Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, host):
        super().__init__()
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.host != 'github.com':
            raise ValueError('This public source must not redirect')
        _url(newurl, GITHUB_REDIRECTS, signed=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_asset(spec, destination, cancel, progress=None):
    if (not isinstance(spec, dict) or type(spec.get('size')) is not int
            or not 0 < spec['size'] <= 512 << 20
            or not isinstance(spec.get('sha256'), str)
            or not re.fullmatch('[a-f0-9]{64}', spec['sha256'])):
        raise ValueError('Invalid public asset pin')
    host = _url(spec.get('url'), INITIAL_HOSTS)
    target = safe_path(destination)
    if target.exists() or not target.parent.is_dir():
        raise ValueError('Download destination must be a new file in an existing directory')
    if cancel.is_set():
        raise RuntimeError('Cancelled')
    ca = Path('/etc/ssl/certs/ca-certificates.crt')
    tls = ssl.create_default_context(cafile=str(ca) if ca.is_file() else None)
    opener = urllib.request.build_opener(_Redirect(host), urllib.request.HTTPSHandler(context=tls))
    partial = target.with_name(target.name + '.part-' + uuid.uuid4().hex)
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    deadline, count, digest = time.monotonic() + 600, 0, hashlib.sha256()
    try:
        with os.fdopen(fd, 'wb') as output:
            request = urllib.request.Request(spec['url'], headers={'User-Agent': 'HelixSR-Decky-Armada-model-setup'})
            with opener.open(request, timeout=10) as response:
                length = response.headers.get('Content-Length')
                if length is not None and int(length) != spec['size']:
                    raise ValueError('Public asset size differs from its pin')
                while True:
                    if cancel.is_set():
                        raise RuntimeError('Cancelled')
                    if time.monotonic() > deadline:
                        raise RuntimeError('Public download timed out')
                    block = response.read(1 << 20)
                    if not block:
                        break
                    count += len(block)
                    if count > spec['size']:
                        raise ValueError('Public asset exceeds its pinned size')
                    digest.update(block)
                    output.write(block)
                    if progress:
                        progress(count, spec['size'])
            output.flush()
            os.fsync(output.fileno())
        if cancel.is_set():
            raise RuntimeError('Cancelled')
        if count != spec['size'] or digest.hexdigest() != spec['sha256']:
            raise ValueError('Public asset failed its size or SHA256 check')
        safe_path(target.parent)
        # Exclusive publication: another file appearing here is never replaced.
        os.link(partial, target)
        return target
    finally:
        partial.unlink(missing_ok=True)


def _name(name, directory):
    if not isinstance(name, str) or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('Unsafe archive member name')
    canonical = name[:-1] if directory and name.endswith('/') else name
    p = PurePosixPath(canonical)
    if (not canonical or p.is_absolute() or any(n in ('.', '..') for n in canonical.split('/'))
            or p.as_posix() != canonical):
        raise ValueError('Unsafe or noncanonical archive member name')
    return canonical


def _inventory(entries, max_bytes):
    if type(max_bytes) is not int or not 0 < max_bytes <= 1 << 30:
        raise ValueError('Invalid extraction limit')
    names, total, plan = set(), 0, []
    for name, directory, size, mode, member in entries:
        name = _name(name, directory)
        key = os.path.normcase(name)
        if key in names or len(names) >= 10000 or size < 0:
            raise ValueError('Archive contains duplicates or excessive entries')
        names.add(key)
        total += size
        if total > max_bytes:
            raise ValueError('Archive exceeds its extraction limit')
        plan.append((name, directory, size, mode, member))
    return plan


def _extract(destination, plan, reader):
    root = safe_path(destination)
    if root.exists() or not root.parent.is_dir():
        raise ValueError('Extraction destination must be a new directory')
    root.mkdir(mode=0o700)
    try:
        for name, directory, size, mode, member in plan:
            p = safe_path(root / name)
            if directory:
                p.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            count = 0
            with reader(member) as source, p.open('xb') as target:
                while True:
                    block = source.read(1 << 20)
                    if not block:
                        break
                    count += len(block)
                    if count > size:
                        raise ValueError('Archive member exceeds declared size')
                    target.write(block)
            if count != size:
                raise ValueError('Archive member has an inconsistent size')
            p.chmod(0o755 if mode & 0o111 else 0o600)
        return root
    except BaseException:
        # The directory was created by this call, never a pre-existing folder.
        shutil.rmtree(root)
        raise


def extract_zip(archive, destination, max_bytes=1 << 30):
    with zipfile.ZipFile(safe_path(archive)) as z:
        entries = []
        for item in z.infolist():
            directory, mode = item.is_dir(), item.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG):
                raise ValueError('ZIP contains a link or special member')
            if item.file_size > max(1, item.compress_size) * 500:
                raise ValueError('ZIP member has excessive compression ratio')
            # ZipInfo normalizes backslashes on Windows; validate raw spelling.
            entries.append((item.orig_filename, directory, item.file_size, mode, item))
        return _extract(destination, _inventory(entries, max_bytes), z.open)


def extract_tar(archive, destination, max_bytes=1 << 30):
    import tarfile
    with tarfile.open(safe_path(archive), 'r:*') as t:
        entries = []
        # Bound parsing as well as extracted payload size.
        count, names = 0, set()
        for item in t:
            count += 1
            if count > 10000:
                raise ValueError('TAR contains excessive entries')
            name = _name(item.name, item.isdir())
            key = os.path.normcase(name)
            if key in names:
                raise ValueError('TAR contains duplicate members')
            names.add(key)
            if item.issym():
                continue  # Standalone Python aliases are unnecessary; create no links.
            if not item.isfile() and not item.isdir():
                raise ValueError('TAR contains a hard link or special member')
            entries.append((item.name, item.isdir(), item.size, item.mode, item))
        return _extract(destination, _inventory(entries, max_bytes), t.extractfile)
