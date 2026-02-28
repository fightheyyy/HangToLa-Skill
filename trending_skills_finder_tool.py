"""
Trending Skills Finder Tool - GitHub 热门 Skill 发现工具
通过 GitHub Search API 搜索包含 SKILL.md 的仓库，
按 star 数和最近活跃度排序，找出最近飙升的 Skill。
"""

import sys
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


from base_tool import BaseTool
from typing import Dict, Any, List, Optional
import requests
import time
from datetime import datetime, timedelta

API_BASE = "https://api.github.com"

# 排除的仓库关键词（模板、示例等）
EXCLUDE_KEYWORDS = {
    'template', 'example', 'demo', 'test', 'boilerplate',
}


class TrendingSkillsFinder(BaseTool):
    """GitHub 热门 Skill 发现工具"""

    tool_name = "trending_skills_finder"
    tool_description = "搜索 GitHub 上包含 SKILL.md 的仓库，按热度排序，找出最近飙升的 Skill。"
    tool_parameters = {
        "type": "object",
        "properties": {
            "max_results": {
                "type": "number",
                "description": "最多返回的 skill 数量（默认 10，最大 20）",
                "default": 10
            },
            "sort_by": {
                "type": "string",
                "description": "排序方式：stars（按星数）、updated（按最近更新）、hot（综合热度，默认）",
                "default": "hot"
            },
            "days": {
                "type": "number",
                "description": "只看最近 N 天内有更新的仓库（默认 30）",
                "default": 30
            },
            "token": {
                "type": "string",
                "description": "GitHub Personal Access Token（可选，提高 API 限额）"
            }
        },
        "required": []
    }
    tool_timeout = 60

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        max_results = min(params.get('max_results', 10), 20)
        sort_by = params.get('sort_by', 'hot')
        days = params.get('days', 30)
        token = params.get('token')

        headers = {'Accept': 'application/vnd.github.v3+json'}
        if token:
            headers['Authorization'] = f'token {token}'

        # Step 1: 搜索包含 SKILL.md 的仓库
        repos = self._search_skill_repos(headers, days)

        # Step 2: 获取每个仓库的详细信息
        enriched = self._enrich_repos(repos, headers)

        # Step 3: 过滤垃圾仓库
        filtered = self._filter_repos(enriched)

        # Step 4: 排序
        sorted_repos = self._sort_repos(filtered, sort_by)

        # Step 5: 截取 top N
        top = sorted_repos[:max_results]

        return {
            'total_found': len(filtered),
            'returned': len(top),
            'sort_by': sort_by,
            'skills': top
        }

    # ── GitHub 搜索 ──

    def _search_skill_repos(self, headers: Dict, days: int) -> List[Dict]:
        """通过 GitHub Code Search 搜索包含 SKILL.md 的仓库"""
        since = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')
        repos_seen = {}

        # 搜索策略：filename:SKILL.md，翻两页拿足够多的结果
        for page in range(1, 3):
            url = f"{API_BASE}/search/code"
            params = {
                'q': f'filename:SKILL.md pushed:>{since}',
                'per_page': 50,
                'page': page,
            }
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=15)
                if resp.status_code == 403:
                    # 限流，等一下重试
                    time.sleep(2)
                    resp = requests.get(url, headers=headers, params=params, timeout=15)
                if resp.status_code != 200:
                    break

                data = resp.json()
                for item in data.get('items', []):
                    repo = item.get('repository', {})
                    full_name = repo.get('full_name', '')
                    if full_name and full_name not in repos_seen:
                        repos_seen[full_name] = {
                            'full_name': full_name,
                            'url': f"https://github.com/{full_name}",
                            'skill_md_path': item.get('path', 'SKILL.md'),
                        }

                # 结果不够一页，不用翻了
                if data.get('total_count', 0) <= page * 50:
                    break

                # Code Search 限流比较严，间隔一下
                time.sleep(1)

            except Exception:
                break

        return list(repos_seen.values())

    # ── 仓库详情补充 ──

    def _enrich_repos(self, repos: List[Dict], headers: Dict) -> List[Dict]:
        """获取每个仓库的 star、描述、最近更新时间等"""
        enriched = []
        for repo in repos:
            full_name = repo['full_name']
            url = f"{API_BASE}/repos/{full_name}"
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                repo['stars'] = data.get('stargazers_count', 0)
                repo['description'] = data.get('description', '')
                repo['language'] = data.get('language', '')
                repo['pushed_at'] = data.get('pushed_at', '')
                repo['created_at'] = data.get('created_at', '')
                repo['forks'] = data.get('forks_count', 0)
                repo['owner'] = data.get('owner', {}).get('login', '')
                enriched.append(repo)
            except Exception:
                continue
            time.sleep(0.3)
        return enriched

    # ── 过滤 ──

    def _filter_repos(self, repos: List[Dict]) -> List[Dict]:
        """过滤掉模板、示例等无意义仓库"""
        filtered = []
        for repo in repos:
            name_lower = repo['full_name'].lower()
            desc_lower = (repo.get('description') or '').lower()
            # 跳过名称或描述中包含排除关键词的
            if any(kw in name_lower or kw in desc_lower for kw in EXCLUDE_KEYWORDS):
                continue
            filtered.append(repo)
        return filtered

    # ── 排序 ──

    def _sort_repos(self, repos: List[Dict], sort_by: str) -> List[Dict]:
        """按指定方式排序"""
        if sort_by == 'stars':
            return sorted(repos, key=lambda r: r.get('stars', 0), reverse=True)

        elif sort_by == 'updated':
            return sorted(repos, key=lambda r: r.get('pushed_at', ''), reverse=True)

        else:
            # hot：综合热度 = stars + 新鲜度加成
            now = datetime.utcnow()
            def hot_score(repo):
                stars = repo.get('stars', 0)
                pushed = repo.get('pushed_at', '')
                freshness = 0
                if pushed:
                    try:
                        pushed_dt = datetime.strptime(pushed[:10], '%Y-%m-%d')
                        days_ago = max((now - pushed_dt).days, 1)
                        freshness = 100 / days_ago  # 越新分越高
                    except Exception:
                        pass
                return stars + freshness * 5

            return sorted(repos, key=hot_score, reverse=True)


if __name__ == '__main__':
    tool = TrendingSkillsFinder()
    tool.run()
