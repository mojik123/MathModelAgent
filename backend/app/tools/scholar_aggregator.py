"""文献检索聚合器，合并 OpenAlex 和 Crossref 双源结果并去重。"""

import asyncio
from typing import List, Dict, Any


class ScholarAggregator:
    """合并多个文献源的搜索客户端，提供统一的 search_papers 接口。"""

    def __init__(self, *sources: Any) -> None:  # 实际是 OpenAlexScholar | CrossrefScholar
        self.sources = list(sources)

    async def search_papers(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        """并发搜索所有源，合并去重后返回。

        去重策略：先按 DOI 匹配，再按标题相似度（小写 + 去空格）匹配。
        """
        per_source_limit = max(limit, 8)
        tasks = [
            source.search_papers(query, limit=per_source_limit)
            for source in self.sources
        ]
        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_papers: List[Dict[str, Any]] = []
        seen_dois: set[str] = set()
        seen_titles: set[str] = set()

        for results in results_lists:
            if isinstance(results, Exception):
                print(f"文献源搜索异常: {results}")
                continue
            for paper in results:
                doi = (paper.get("doi") or "").strip().lower()
                title_key = (
                    (paper.get("title") or "").strip().lower().replace(" ", "")
                )

                if doi and doi in seen_dois:
                    continue
                if title_key and title_key in seen_titles:
                    continue

                if doi:
                    seen_dois.add(doi)
                if title_key:
                    seen_titles.add(title_key)
                all_papers.append(paper)

        # 按引用次数降序排序
        all_papers.sort(
            key=lambda p: p.get("citations_count") or 0,
            reverse=True,
        )
        return all_papers[:limit]

    def papers_to_str(self, papers: List[Dict[str, Any]]) -> str:
        """将文献列表转换为可读字符串，使用第一源的格式化方法。"""
        if self.sources:
            return self.sources[0].papers_to_str(papers)
        result = ""
        for paper in papers:
            result += f"\n{'='*80}\n标题: {paper['title']}\n摘要: {paper.get('abstract', '')}\n{'='*80}"
        return result
