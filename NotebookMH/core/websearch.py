"""core/websearch.py — 联网搜索（多引擎聚合，国内服务器可用）"""
import logging
from urllib.parse import quote

log = logging.getLogger(__name__)

_BING = "https://cn.bing.com/search?q={q}&setlang=zh-CN&ensearch=0"
_DDG = "https://lite.duckduckgo.com/lite/?q={q}"
_SOUGOU = "https://www.sogou.com/web?query={q}"


def _search_bing(query: str, max_results: int) -> list[dict]:
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
        log.debug("Bing 搜索失败 [%s]: %s", query, e)
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
    log.debug("Bing [%s] 返回 %d 条", query, len(out))
    return out


def _search_ddg(query: str, max_results: int) -> list[dict]:
    import httpx
    from bs4 import BeautifulSoup
    from core.parsers import _URL_HEADERS

    url = _DDG.format(q=quote(query))
    try:
        with httpx.Client(timeout=20, follow_redirects=True,
                          headers=_URL_HEADERS) as client:
            r = client.get(url)
            r.raise_for_status()
            html = r.text
    except Exception as e:
        log.debug("DDG 搜索失败 [%s]: %s", query, e)
        return []

    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for tr in soup.select("table.result-table tr"):
        tds = tr.select("td")
        if len(tds) < 2:
            continue
        link_a = tds[1].select_one("a.result-link")
        if not link_a or not link_a.get("href"):
            continue
        link = link_a["href"]
        if not link.startswith("http"):
            continue
        title = link_a.get_text(strip=True)
        snippet = tds[1].get_text(strip=True).replace(title, "").strip()
        out.append({"title": title, "url": link, "snippet": snippet})
        if len(out) >= max_results:
            break
    log.debug("DDG [%s] 返回 %d 条", query, len(out))
    return out


def _search_sogou(query: str, max_results: int) -> list[dict]:
    import httpx
    from bs4 import BeautifulSoup
    from core.parsers import _URL_HEADERS

    url = _SOUGOU.format(q=quote(query))
    try:
        with httpx.Client(timeout=20, follow_redirects=True,
                          headers=_URL_HEADERS) as client:
            r = client.get(url)
            r.raise_for_status()
            html = r.text
    except Exception as e:
        log.debug("Sogou 搜索失败 [%s]: %s", query, e)
        return []

    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for vrwrap in soup.select("div.vrwrap"):
        h3 = vrwrap.select_one("h3 a")
        if not h3 or not h3.get("href"):
            continue
        link = h3["href"]
        if link.startswith("/"):
            link = "https://www.sogou.com" + link
        if not link.startswith("http"):
            continue
        title = h3.get_text(strip=True)
        # 过滤搜狗自己的广告/推广
        if "sogou.com" in link or "soso.com" in link:
            continue
        snippet = ""
        p = vrwrap.select_one("p.str_info") or vrwrap.select_one("p")
        if p:
            snippet = p.get_text(strip=True)
        out.append({"title": title, "url": link, "snippet": snippet})
        if len(out) >= max_results:
            break
    log.debug("Sogou [%s] 返回 %d 条", query, len(out))
    return out


def search(query: str, max_results: int = 5) -> list[dict]:
    """多引擎聚合搜索，返回 [{title, url, snippet}]。"""
    all_results: list[dict] = []
    seen_urls: set[str] = set()

    engines = [_search_bing, _search_ddg, _search_sogou]
    per_engine = max(3, max_results // len(engines) + 1)

    for engine in engines:
        try:
            results = engine(query, per_engine)
            for r in results:
                u = r["url"]
                if u in seen_urls:
                    continue
                seen_urls.add(u)
                all_results.append(r)
                if len(all_results) >= max_results:
                    break
        except Exception as e:
            log.debug("引擎 %s 失败: %s", engine.__name__, e)
        if len(all_results) >= max_results:
            break

    log.info("搜索 [%s] 聚合结果: %d 条", query, len(all_results))
    return all_results[:max_results]
