"""Recipe preview images served through the NAS.

Browsers never contact the Cookidoo CDN directly: the page keeps its strict
CSP (img-src 'self') and no family device leaks requests to third parties
(D-01). The NAS fetches each preview once from an allowlisted HTTPS host,
checks type and size and keeps a small on-disk cache.

The client only ever passes a recipe ID. The source URL comes from data the
NAS itself received from Cookidoo, so the endpoint cannot be used to fetch
arbitrary URLs (no SSRF).
"""
import hashlib
import logging
from pathlib import Path
import re
import time
from urllib.parse import urlparse

import httpx

LOG = logging.getLogger('uvicorn.error.family_os.images')
ALLOWED_HOSTS = ('assets.tmecosys.com',)
ALLOWED_SUFFIXES = ('.tmecosys.com',)
TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/avif': 'avif'}
MAX_BYTES = 2 * 1024 * 1024
MAX_FILES = 400
RECIPE_ID = re.compile(r'^r[0-9]+$')
FAILURE_PAUSE = 3600


def allowed(url):
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or '').lower()
    return (parsed.scheme == 'https' and parsed.port in (None, 443) and not parsed.username and not parsed.password
            and (host in ALLOWED_HOSTS or host.endswith(ALLOWED_SUFFIXES)))


class RecipeImages:
    def __init__(self, db, directory, demo, fetch=None):
        self.db, self.demo = db, demo
        self.directory = Path(directory) / 'recipe-images'
        self.fetch = fetch or self._fetch
        self.failed = {}

    def remember(self, images):
        """Store thumbnail URLs reported by Cookidoo: {recipe_id: url}."""
        rows = [('image:' + rid, url, time.time()) for rid, url in images.items() if RECIPE_ID.match(rid) and url and allowed(url)]
        if rows:
            with self.db() as conn:
                conn.executemany('INSERT OR REPLACE INTO meal_cache VALUES(?,?,?)', rows)

    def available(self, recipe_ids):
        """Map of recipe IDs with a known preview to their local image path."""
        ids = sorted({rid for rid in recipe_ids if RECIPE_ID.match(rid or '')})
        if not ids:
            return {}
        with self.db() as conn:
            marks = ','.join('?' * len(ids))
            known = [row[0][6:] for row in conn.execute(f'SELECT key FROM meal_cache WHERE key IN ({marks})', ['image:' + rid for rid in ids])]
        return {rid: '/api/meals/image/' + rid for rid in known}

    def _fetch(self, url):
        with httpx.Client(timeout=8, follow_redirects=False) as client:
            with client.stream('GET', url, headers={'Accept': 'image/avif,image/webp,image/jpeg,image/png'}) as response:
                if response.status_code != 200:
                    raise ValueError(f'status {response.status_code}')
                kind = response.headers.get('content-type', '').split(';')[0].strip().lower()
                if kind not in TYPES:
                    raise ValueError('unexpected content type')
                data = b''
                for chunk in response.iter_bytes():
                    data += chunk
                    if len(data) > MAX_BYTES:
                        raise ValueError('image too large')
                return kind, data

    def cached(self, url):
        name = hashlib.sha256(url.encode()).hexdigest()
        for kind, ext in TYPES.items():
            path = self.directory / f'{name}.{ext}'
            if path.exists():
                return kind, path
        return None, None

    def prune(self):
        files = sorted(self.directory.glob('*.*'), key=lambda p: p.stat().st_mtime)
        for path in files[:max(0, len(files) - MAX_FILES)]:
            path.unlink(missing_ok=True)

    def get(self, rid):
        """Return (content_type, path) or None if no preview is available."""
        if self.demo or not RECIPE_ID.match(rid):
            return None
        with self.db() as conn:
            row = conn.execute('SELECT value FROM meal_cache WHERE key=?', ('image:' + rid,)).fetchone()
        if not row or not allowed(row[0]):
            return None
        url = row[0]
        kind, path = self.cached(url)
        if path:
            return kind, path
        if time.time() - self.failed.get(url, 0) < FAILURE_PAUSE:
            return None
        try:
            kind, data = self.fetch(url)
        except Exception as error:
            # Never log the URL or response body; a short reason is enough.
            LOG.warning('Rezeptbild nicht geladen recipe=%s reason=%s', rid, type(error).__name__)
            self.failed[url] = time.time()
            return None
        self.directory.mkdir(mode=0o700, exist_ok=True)
        path = self.directory / f'{hashlib.sha256(url.encode()).hexdigest()}.{TYPES[kind]}'
        temporary = path.with_suffix('.part')
        temporary.write_bytes(data)
        temporary.replace(path)
        self.prune()
        return kind, path
