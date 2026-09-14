"""Small allow-listed RSS reader for recommendation context."""
from __future__ import annotations
import xml.etree.ElementTree as ET
import httpx
from datetime import datetime, timezone


async def fetch_rss_headlines(urls: str) -> list[dict[str, str]]:
    headlines: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers={"User-Agent": "FantasyEdge/1.0 (personal research)"}) as client:
        for url in [value.strip() for value in urls.split(",") if value.strip()]:
            # A rate-limited or malformed third-party feed must not make the
            # entire advice endpoint unavailable; the response remains
            # explicitly bounded to the sources that did succeed.
            try:
                response = await client.get(url)
                response.raise_for_status()
                root = ET.fromstring(response.content)
            except (httpx.HTTPError, ET.ParseError):
                continue
            for item in root.findall(".//item")[:10]:
                title = item.findtext("title")
                link = item.findtext("link")
                if title and link:
                    headlines.append({"title": title.strip(), "url": link.strip(), "source": url,
                        "published_at_raw": item.findtext('pubDate') or '',
                        "observed_at": datetime.now(timezone.utc).isoformat()})
            # Reddit and many modern publications serve Atom rather than RSS.
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:10]:
                title = entry.findtext("{http://www.w3.org/2005/Atom}title")
                link_node = entry.find("{http://www.w3.org/2005/Atom}link[@href]")
                if title and link_node is not None and link_node.get("href"):
                    headlines.append({"title": title.strip(), "url": link_node.get("href", ""), "source": url,
                        "published_at_raw": entry.findtext('{http://www.w3.org/2005/Atom}published') or '',
                        "observed_at": datetime.now(timezone.utc).isoformat()})
    return headlines[:30]
