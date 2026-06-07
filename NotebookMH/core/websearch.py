"""core/websearch.py — 联网搜索（优先 Tavily API，回退多引擎爬虫）"""
import logging
from urllib.parse import quote

from config import TAVILY_API_KEY, USE_TAVILY

log = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"


def _search_tavily(query: str, max_results: int) -> list[dict]:
    """Tavily 专业搜索 API：返回干净、相关的结构化结果。"""
    import httpx

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "include_answer": False,
        "include_raw_content": False,
    }
    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(_TAVILY_URL, json=payload)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("Tavily 搜索失败 [%s]: %s", query, e)
        return []

    out: list[dict] = []
    for item in data.get("results", []):
        url = item.get("url", "")
        if not url.startswith("http"):
            continue
        out.append({
            "title": item.get("title", "") or url,
            "url": url,
            "snippet": item.get("content", "")[:300],
        })
    log.info("Tavily [%s] 返回 %d 条", query, len(out))
    return out

_BING = "https://cn.bing.com/search?q={q}&setlang=zh-CN&ensearch=0"
_DDG = "https://lite.duckduckgo.com/lite/?q={q}"
_SOUGOU = "https://www.sogou.com/web?query={q}"


def _search_bing(query: str, max_results: int) -> list[dict]:
    import httpx
    from bs4 import BeautifulSoup
    from core.parsers import _URL_HEADERS

    url = _BING.format(q=quote(query))
    try:
        with httpx.Client(timeout=8, follow_redirects=True,
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
        with httpx.Client(timeout=8, follow_redirects=True,
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
        with httpx.Client(timeout=8, follow_redirects=True,
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
    """搜索：优先 Tavily API（高质量），失败回退多引擎爬虫。"""
    # ── 优先 Tavily ──
    if USE_TAVILY:
        results = _search_tavily(query, max_results)
        if results:
            return results
        log.info("Tavily 无结果，回退爬虫引擎 [%s]", query)

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
