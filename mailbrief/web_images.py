"""Linked images in emails (newsletters load their posters from the web), downloaded for the vision model.

The URLs come from email bodies, so they're untrusted: https only, never an address on your own network
(checked after resolving the name), no redirects (a redirect could point anywhere), no cookies, small caps.
Downloaded images live in memory only, like attachment images. REMOTE_IMAGES=off turns this off.
"""

import base64
import ipaddress
import os
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from mailbrief.browser.owa_network import IMAGE_MAX, IMAGE_MIN

TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
TRIES = 12      # URLs tried per email at most
TIMEOUT_S = 10  # per connect and per read: a server that goes quiet
TOTAL_S = 20    # per image, start to finish: a server that drips a few bytes just inside every read timeout


def enabled() -> bool:
    return os.environ.get("REMOTE_IMAGES", "on").strip().lower() not in ("off", "0", "false", "no")


def _resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]


def allowed(url: str, resolve=_resolve) -> bool:
    """True for an https URL whose host resolves only to public internet addresses.
    ponytail: the name is resolved again when connecting (DNS rebinding); connect to the checked IP if that matters."""
    parts = urlparse(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    try:
        addresses = resolve(parts.hostname)
    except (OSError, UnicodeError):
        return False
    return bool(addresses) and all(_public(a) for a in addresses)


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _public(address: str) -> bool:
    """A public internet address: not private, loopback, link-local, reserved, CGNAT or multicast, and not an
    IPv6 form that carries one of those IPv4 addresses inside it (which is_global alone lets through)."""
    ip = ipaddress.ip_address(address.split("%")[0])
    if ip.version == 6:
        inner = ip.ipv4_mapped or ip.sixtofour  # ::ffff:a.b.c.d, 2002:AABB:CCDD::
        if inner is None and (ip in _NAT64 or int(ip) >> 32 == 0):  # 64:ff9b::a.b.c.d (NAT64), ::a.b.c.d
            inner = ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
        if inner is not None:
            return inner.is_global and not inner.is_multicast
    return ip.is_global and not ip.is_multicast


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a 3xx becomes an error: never follow it


_opener = urllib.request.build_opener(_NoRedirect)


def _read(stream, limit: int, total_s: float = TOTAL_S, clock=time.monotonic) -> bytes:
    """Up to `limit` bytes, giving up (TimeoutError) once the whole download has taken total_s. The socket
    timeout alone only bounds each read, so a slow drip could hold a run, and the run lock, for days."""
    deadline, data = clock() + total_s, b""
    read = getattr(stream, "read1", None) or stream.read  # read1: whatever has arrived, not "block until 64 KB have"
    while len(data) < limit:
        if clock() > deadline:
            raise TimeoutError("image download took too long")
        chunk = read(min(65536, limit - len(data)))
        if not chunk:
            break
        data += chunk
    return data


def _fetch(url: str) -> tuple[str, bytes]:
    """(content type, up to IMAGE_MAX + 1 bytes). Raises on any HTTP or network problem."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
    with _opener.open(req, timeout=TIMEOUT_S) as r:
        return (r.headers.get("Content-Type") or "").split(";")[0].strip().lower(), _read(r, IMAGE_MAX + 1)


def download(urls: list[str], room: int, budget: int, fetch=_fetch, check=allowed) -> list[str]:
    """Up to `room` images (data URLs) totalling at most `budget` bytes. Anything odd is skipped, never raised."""
    out = []
    for url in urls[:TRIES]:
        if len(out) >= room or budget < IMAGE_MIN:
            break
        try:
            if not check(url):
                continue
            ctype, data = fetch(url)
        except Exception:  # noqa: BLE001 - a broken image link must never cost the email its classification
            continue
        if ctype in TYPES and IMAGE_MIN <= len(data) <= min(IMAGE_MAX, budget):
            out.append(f"data:{ctype};base64,{base64.b64encode(data).decode()}")
            budget -= len(data)
    return out
