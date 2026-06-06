"""core/websearch.py — 联网搜索（Bing 网页版抓取，国内服务器可用）"""
import logging
from urllib.parse import quote

log = logging.getLogger(__name__)

_BING = "https://cn.bing.com/search?q={q}&setlang=zh-CN&ensearch=0"


def search(query: str, max_results: int = 5) -> list[dict]:
    """搜索并返回 [{title, url, snippet}]。失败返回 []。"""
    import httpx
    from bs4 import BeautifulSoup
    from core.parsers import _URL_HEADERS

    url = _BING.format(q=quote(query))
    try:
        with httpx.Client(timeout=20, follow_redirects=True,
                          headers=_URL_HEADERS) as client:
            r = client.get(url)
            r.raise_for_status()
            html = r.text
    except Exception as e:
        log.warning("Bing 搜索失败 [%s]: %s", query, e)
        return []

    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if not a or not a.get("href"):
            continue
        link = a["href"]
        if not link.startswith("http"):
            continue
        title = a.get_text(strip=True)
        snippet_el = li.select_one(".b_caption p") or li.select_one("p")
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
        out.append({"title": title, "url": link, "snippet": snippet})
        if len(out) >= max_results:
            break
    return out
