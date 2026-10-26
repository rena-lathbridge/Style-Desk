"""Fetching images the user points us at, without becoming an open proxy.

A URL box is a server-side request forgery surface: whatever the user types,
our server fetches, from inside whatever network it is running on. So every
hop is resolved and checked against private address space before we connect,
redirects are followed by hand rather than by the library, and anything that
does not come back as an image is dropped.
"""

from __future__ import annotations

import ipaddress
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

MAX_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT = 12
MAX_URLS = 6

# Pinterest serves board pages as an empty shell and fills them in with an
# authenticated XHR, so there is nothing for a server to scrape. Their
# robots.txt also disallows everything outside an allowlist. We recognize
# board links only so we can explain that, rather than fail silently.
_BOARD_HOSTS = {"pinterest.com", "www.pinterest.com", "pin.it", "uk.pinterest.com"}

_UA = "StyleDesk/1.0 (course project; fetches only images the user pastes)"


def _ssl_context() -> ssl.SSLContext:
    """Prefer the operating system's trust store.

    Python ships its own CA bundle, which fails on any machine behind a TLS
    inspecting proxy — common on corporate and university laptops. truststore
    borrows the OS store instead; without it we fall back to the default.
    """
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return ssl.create_default_context()


_SSL = _ssl_context()


class FetchRefused(ValueError):
    """The URL was rejected before, or during, the request."""


@dataclass
class Fetched:
    url: str
    data: bytes
    content_type: str


def is_board_link(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _BOARD_HOSTS


def _check_host(host: str) -> None:
    """Resolve every address for the host and refuse anything not public."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchRefused(f"Could not resolve {host}.") from exc

    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise FetchRefused(
                f"{host} resolves to a non-public address ({addr}). "
                "Only public image URLs are allowed."
            )


def fetch_image(url: str) -> Fetched:
    """Fetch one image URL, checking every redirect hop as its own request."""
    seen = url
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlparse(seen)
        if parts.scheme != "https":
            raise FetchRefused("Only https URLs are allowed.")
        if not parts.hostname:
            raise FetchRefused("That does not look like a URL.")
        _check_host(parts.hostname)

        request = urllib.request.Request(seen, headers={"User-Agent": _UA})
        # Redirects are handled here, so each new host gets checked too.
        opener = urllib.request.build_opener(
            _NoRedirect, urllib.request.HTTPSHandler(context=_SSL)
        )
        try:
            with opener.open(request, timeout=TIMEOUT) as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise FetchRefused("Redirect without a destination.")
                    seen = urllib.parse.urljoin(seen, location)
                    continue

                ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip()
                if not ctype.startswith("image/"):
                    raise FetchRefused(
                        f"That URL returned {ctype or 'no content type'}, not an image. "
                        "Use a direct link to the image itself."
                    )
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > MAX_BYTES:
                    raise FetchRefused("That image is larger than 8 MB.")

                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise FetchRefused("That image is larger than 8 MB.")
                if not data:
                    raise FetchRefused("That URL returned an empty file.")
                return Fetched(url=seen, data=data, content_type=ctype)

        except urllib.error.HTTPError as exc:
            raise FetchRefused(f"That URL returned HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise FetchRefused(f"Could not reach that URL ({exc.reason}).") from exc
        except TimeoutError as exc:
            raise FetchRefused("That URL took too long to respond.") from exc

    raise FetchRefused("Too many redirects.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand redirects back to us instead of following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

    def http_error_301(self, req, fp, code, msg, headers):
        return fp

    http_error_302 = http_error_303 = http_error_307 = http_error_308 = http_error_301
