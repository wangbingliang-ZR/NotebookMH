"""诊断搜索全链路 —— 在服务器上运行，定位到底哪一环返回空。

用法（服务器）:
    cd /opt/notebookmh && source venv/bin/activate
    python3 diagnose_search.py "河北中考生物"
"""
import sys
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from core.websearch import _search_bing, _search_ddg, _search_sogou, _search_tavily, search
from config import USE_TAVILY

TOPIC = sys.argv[1] if len(sys.argv) > 1 else "河北中考生物真题"


def stage0_tavily():
    print("\n" + "=" * 60)
    print(f"阶段0：Tavily API  (USE_TAVILY={USE_TAVILY})")
    print("=" * 60)
    if not USE_TAVILY:
        print("未配置 TAVILY_API_KEY，跳过。请在 .env 添加后重试。")
        return
    res = _search_tavily(TOPIC, 8)
    print(f"Tavily 返回 {len(res)} 条")
    for r in res[:5]:
        print(f"   - {r['title'][:45]}  |  {r['url'][:60]}")


def stage1_engines():
    print("\n" + "=" * 60)
    print(f"阶段1：三个搜索引擎分别返回多少条  查询词=「{TOPIC}」")
    print("=" * 60)
    for name, fn in [("Bing", _search_bing), ("DuckDuckGo", _search_ddg), ("Sogou", _search_sogou)]:
        try:
            res = fn(TOPIC, 8)
            print(f"\n[{name}] 返回 {len(res)} 条")
            for r in res[:3]:
                print(f"   - {r['title'][:40]}  |  {r['url'][:60]}")
        except Exception as e:
            print(f"\n[{name}] 异常: {e!r}")


def stage1b_raw_html():
    """如果引擎返回 0 条，看是网络问题还是解析问题。"""
    print("\n" + "=" * 60)
    print("阶段1b：检查是否能拿到搜索引擎的原始 HTML（区分网络 vs 解析）")
    print("=" * 60)
    import httpx
    from urllib.parse import quote
    from core.parsers import _URL_HEADERS
    urls = {
        "Bing": f"https://cn.bing.com/search?q={quote(TOPIC)}",
        "DuckDuckGo": f"https://lite.duckduckgo.com/lite/?q={quote(TOPIC)}",
        "Sogou": f"https://www.sogou.com/web?query={quote(TOPIC)}",
    }
    for name, url in urls.items():
        try:
            with httpx.Client(timeout=10, follow_redirects=True, headers=_URL_HEADERS) as c:
                r = c.get(url)
                print(f"\n[{name}] HTTP {r.status_code}  HTML 长度={len(r.text)}")
                # 关键词探测：页面里有没有结果区块的标志
                markers = {
                    "Bing": ["b_algo", "b_results"],
                    "DuckDuckGo": ["result-link", "result-table"],
                    "Sogou": ["vrwrap", "results"],
                }[name]
                for m in markers:
                    print(f"     含 '{m}': {m in r.text}")
        except Exception as e:
            print(f"\n[{name}] 网络异常: {e!r}")


def stage2_aggregate():
    print("\n" + "=" * 60)
    print("阶段2：聚合搜索 search() 总共返回多少条")
    print("=" * 60)
    res = search(TOPIC, max_results=10)
    print(f"聚合返回 {len(res)} 条")
    for r in res[:5]:
        print(f"   - {r['title'][:40]}  |  {r['url'][:60]}")
    return res


async def stage3_pipeline():
    print("\n" + "=" * 60)
    print("阶段3：完整 plan_and_discover 流程")
    print("=" * 60)
    from core.research import plan_and_discover
    cands = await plan_and_discover(TOPIC, max_total=20)
    print(f"\n最终候选：{len(cands)} 条")
    for c in cands[:5]:
        print(f"   - [{c.get('category')}] {c['title'][:40]}  |  {c['url'][:50]}")


if __name__ == "__main__":
    stage0_tavily()
    stage1_engines()
    stage1b_raw_html()
    agg = stage2_aggregate()
    if agg:
        asyncio.run(stage3_pipeline())
    else:
        print("\n>>> 搜索引擎返回 0 条，问题在【搜索引擎层】，不用看后面。")
