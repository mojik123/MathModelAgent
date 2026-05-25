"""Crossref 学术文献搜索模块。"""

import requests
from typing import List, Dict, Any
from app.services.redis_manager import redis_manager
from app.schemas.response import ScholarMessage


class CrossrefScholar:
    """Crossref 学术文献搜索客户端（免费，无需注册）。"""

    BASE_URL = "https://api.crossref.org"

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id

    async def search_papers(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        """使用 Crossref API 搜索学术论文。

        Args:
            query: 搜索关键词。
            limit: 最大返回结果数。

        Returns:
            包含论文详细信息的字典列表。
        """
        params = {
            "query": query,
            "rows": min(limit, 50),
            "sort": "relevance",
        }
        url = f"{self.BASE_URL}/works"

        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Crossref 搜索失败: {e}")
            return []

        papers = []
        paper_titles = []
        for item in data.get("message", {}).get("items", []):
            authors = []
            for author in item.get("author", []) or []:
                authors.append({
                    "name": f"{author.get('given', '')} {author.get('family', '')}".strip(),
                    "position": None,
                    "institution": None,
                })

            paper = {
                "title": item.get("title", [""])[0] if item.get("title") else "",
                "abstract": item.get("abstract", ""),
                "authors": authors,
                "citations_count": item.get("is-referenced-by-count", 0),
                "doi": item.get("DOI"),
                "publication_year": item.get("created", {}).get("date-parts", [[None]])[0][0],
                "citation_info": {},
                "citation_format": self._format_citation(item),
            }
            papers.append(paper)
            paper_titles.append(paper["title"])

        await redis_manager.publish_message(
            self.task_id,
            ScholarMessage(
                input={"query": query, "source": "crossref"},
                output=paper_titles,
            ),
        )
        return papers

    def papers_to_str(self, papers: List[Dict[str, Any]]) -> str:
        """将文献列表转换为可读字符串。"""
        result = ""
        for paper in papers:
            result += "\n" + "=" * 80
            result += f"\n标题: {paper['title']}"
            result += f"\n摘要: {paper['abstract']}"
            result += "\n作者:"
            for author in paper["authors"]:
                result += f"\n  - {author['name']}"
            result += f"\n引用次数: {paper['citations_count']}"
            result += f"\n发表年份: {paper['publication_year']}"
            result += f"\n引用格式:\n{paper['citation_format']}"
            result += f"\n来源: Crossref"
            result += "\n" + "=" * 80
        return result

    def _format_citation(self, item: Dict[str, Any]) -> str:
        authors_list = item.get("author", []) or []
        author_names = [
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in authors_list
        ]
        if len(author_names) > 3:
            authors_str = f"{author_names[0]} et al."
        else:
            authors_str = ", ".join(author_names)

        title = (item.get("title") or [""])[0]
        year_parts = item.get("created", {}).get("date-parts", [[None]])[0]
        year = year_parts[0] if year_parts else ""
        doi = item.get("DOI", "")

        citation = f"{authors_str} ({year}). {title}."
        if doi:
            citation += f" DOI: {doi}"
        return citation
