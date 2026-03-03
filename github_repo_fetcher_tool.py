"""
GitHub Repo Fetcher Tool - GitHub 仓库内容抓取工具
输入 GitHub 仓库 URL，自动拉取目录结构和关键文件内容，输出结构化结果。
专为 Skill 评价场景设计，重点抓取 SKILL.md、README.md、工具代码等。
"""

import sys
import os

# 强制 stdout 使用 UTF-8，避免 Windows GBK 编码炸掉
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools', 'global'))

from base_tool import BaseTool
from typing import Dict, Any, List, Optional, Tuple
import requests
import re
import time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed


# GitHub Raw 内容基础 URL
RAW_BASE = "https://raw.githubusercontent.com"
API_BASE = "https://api.github.com"

# 重点关注的文件模式（按优先级排序）
PRIORITY_PATTERNS = [
    r'SKILL\.md$',
    r'README\.md$',
    r'readme\.md$',
    r'\.md$',
]

# 代码文件后缀（次优先级）
CODE_EXTENSIONS = {'.py', '.js', '.ts', '.sh', '.yaml', '.yml', '.toml', '.json'}

# 忽略的路径模式
IGNORE_PATTERNS = [
    r'node_modules/', r'\.git/', r'__pycache__/', r'\.venv/',
    r'dist/', r'build/', r'\.egg-info/', r'\.lock$',
    r'package-lock\.json$', r'yarn\.lock$',
]

# 单文件最大字符数
MAX_FILE_CHARS = 15000
# 总输出最大字符数
MAX_TOTAL_CHARS = 80000


class GitHubRepoFetcher(BaseTool):
    """GitHub 仓库内容抓取工具"""

    tool_name = "github_repo_fetcher"
    tool_description = "输入 GitHub 仓库 URL，自动抓取目录结构和关键文件内容。专为评价 Skill 仓库设计。"
    tool_parameters = {
        "type": "object",
        "properties": {
            "repo_url": {
                "type": "string",
                "description": "GitHub 仓库 URL，如 https://github.com/owner/repo"
            },
            "branch": {
                "type": "string",
                "description": "分支名（默认 main，失败自动尝试 master）",
                "default": "main"
            },
            "token": {
                "type": "string",
                "description": "GitHub Personal Access Token（可选，提高 API 限额）"
            },
            "max_files": {
                "type": "number",
                "description": "最多抓取的文件数量（默认 30）",
                "default": 30
            }
        },
        "required": ["repo_url"]
    }
    tool_timeout = 120

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_params(params, ['repo_url'])

        repo_url = params['repo_url'].rstrip('/')
        branch = params.get('branch', 'main')
        token = params.get('token')
        max_files = min(params.get('max_files', 30), 50)

        # 解析 owner/repo
        owner, repo = self._parse_repo_url(repo_url)

        # 构建请求 headers
        headers = {'Accept': 'application/vnd.github.v3+json'}
        if token:
            headers['Authorization'] = f'token {token}'

        # Step 1: 获取目录树
        tree, branch_used = self._fetch_tree(owner, repo, branch, headers)

        # Step 2: 过滤 + 排序文件
        files = self._filter_and_rank(tree)

        # Step 3: 批量拉取文件内容（取 top N）
        targets = files[:max_files]
        fetched = self._batch_fetch(owner, repo, branch_used, targets, headers)

        # Step 4: 组装输出
        return {
            'repo': f'{owner}/{repo}',
            'branch': branch_used,
            'total_files_in_repo': len(tree),
            'fetched_count': len(fetched),
            'tree_overview': self._build_tree_overview(tree),
            'files': fetched
        }

    # ── URL 解析 ──

    @staticmethod
    def _parse_repo_url(url: str) -> Tuple[str, str]:
        """从 GitHub URL 中提取 owner 和 repo"""
        url = url.rstrip('/')
        # 去掉 .git 后缀
        if url.endswith('.git'):
            url = url[:-4]

        parsed = urlparse(url)
        parts = [p for p in parsed.path.split('/') if p]

        if len(parts) < 2:
            raise ValueError(f"无法解析仓库地址: {url}，需要 https://github.com/owner/repo 格式")

        return parts[0], parts[1]

    # ── 目录树获取 ──

    def _fetch_tree(self, owner: str, repo: str, branch: str, headers: Dict) -> Tuple[List[Dict], str]:
        """获取仓库目录树，API 失败则降级到页面解析"""
        # 尝试 API
        for b in [branch, 'master'] if branch == 'main' else [branch]:
            tree = self._fetch_tree_api(owner, repo, b, headers)
            if tree is not None:
                return tree, b

        # API 全部失败，降级：用 raw 探测常见文件
        tree = self._probe_common_files(owner, repo, branch)
        return tree, branch

    def _fetch_tree_api(self, owner: str, repo: str, branch: str, headers: Dict) -> Optional[List[Dict]]:
        """通过 GitHub API 获取目录树"""
        url = f"{API_BASE}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 403:
                # 限流，返回 None 走降级
                return None
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return [
                {'path': item['path'], 'type': item['type'], 'size': item.get('size', 0)}
                for item in data.get('tree', [])
                if item['type'] == 'blob'
            ]
        except Exception:
            return None

    def _probe_common_files(self, owner: str, repo: str, branch: str) -> List[Dict]:
        """降级方案：探测常见文件路径是否存在"""
        common_paths = [
            'README.md', 'readme.md', 'SKILL.md',
            'skills/SKILL.md', 'src/SKILL.md',
            'package.json', 'pyproject.toml', 'setup.py',
            'requirements.txt', 'Cargo.toml',
        ]
        # 通用 skills 目录探测（不硬编码具体 skill 名）
        # 如果 README.md 存在，后续会从中提取更多线索
        common_paths.append('skills/SKILL.md')

        found = []
        for path in common_paths:
            url = f"{RAW_BASE}/{owner}/{repo}/{branch}/{path}"
            try:
                resp = requests.head(url, timeout=5, allow_redirects=True)
                if resp.status_code == 200:
                    found.append({'path': path, 'type': 'blob', 'size': 0})
            except Exception:
                continue
        return found

    # ── 文件过滤与排序 ──

    def _filter_and_rank(self, tree: List[Dict]) -> List[Dict]:
        """过滤无关文件，按重要性排序"""
        filtered = []
        for item in tree:
            path = item['path']
            # 跳过忽略模式
            if any(re.search(p, path) for p in IGNORE_PATTERNS):
                continue
            # 跳过二进制 / 大文件
            ext = os.path.splitext(path)[1].lower()
            if ext in {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.woff', '.woff2',
                       '.ttf', '.eot', '.mp4', '.mp3', '.zip', '.tar', '.gz', '.pdf',
                       '.exe', '.dll', '.so', '.dylib', '.bin', '.dat', '.pkl', '.pth',
                       '.onnx', '.pb', '.h5', '.safetensors'}:
                continue
            filtered.append(item)

        # 计算优先级分数
        def score(item):
            path = item['path']
            # SKILL.md 最高优先
            if re.search(r'SKILL\.md$', path):
                return 0
            if re.search(r'README\.md$', path, re.IGNORECASE):
                return 1
            # 其他 .md 文件
            if path.endswith('.md'):
                return 2
            # 代码文件
            ext = os.path.splitext(path)[1].lower()
            if ext in CODE_EXTENSIONS:
                # 浅层文件优先
                depth = path.count('/')
                return 3 + depth
            return 10

        filtered.sort(key=score)
        return filtered

    # ── 批量内容拉取 ──

    def _batch_fetch(self, owner: str, repo: str, branch: str,
                     targets: List[Dict], headers: Dict) -> List[Dict]:
        """并发拉取文件内容，控制总量"""
        results = []
        total_chars = 0

        def fetch_one(item):
            path = item['path']
            url = f"{RAW_BASE}/{owner}/{repo}/{branch}/{path}"
            try:
                resp = requests.get(url, timeout=10, headers=headers)
                if resp.status_code != 200:
                    return {'path': path, 'content': None, 'error': f'HTTP {resp.status_code}'}
                text = resp.text[:MAX_FILE_CHARS]
                truncated = len(resp.text) > MAX_FILE_CHARS
                return {
                    'path': path,
                    'content': text,
                    'chars': len(text),
                    'truncated': truncated,
                    'error': None
                }
            except Exception as e:
                return {'path': path, 'content': None, 'error': str(e)}

        # 并发拉取（最多 5 线程）
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(fetch_one, t): t for t in targets}
            for future in as_completed(futures):
                result = future.result()
                if result['content'] is not None:
                    total_chars += result['chars']
                    if total_chars > MAX_TOTAL_CHARS:
                        result['content'] = result['content'][:1000] + '\n\n... [内容截断：总量已达上限] ...'
                        result['truncated'] = True
                results.append(result)

        # 按原始顺序排序
        path_order = {t['path']: i for i, t in enumerate(targets)}
        results.sort(key=lambda r: path_order.get(r['path'], 999))
        return results

    # ── 目录树概览 ──

    @staticmethod
    def _build_tree_overview(tree: List[Dict]) -> str:
        """生成简洁的目录树文本"""
        if not tree:
            return "(无法获取目录树)"

        lines = []
        dirs_seen = set()
        for item in tree:
            path = item['path']
            parts = path.split('/')
            # 添加目录层级
            for i in range(len(parts) - 1):
                dir_path = '/'.join(parts[:i + 1])
                if dir_path not in dirs_seen:
                    dirs_seen.add(dir_path)
                    indent = '  ' * i
                    lines.append(f"{indent}{parts[i]}/")
            # 添加文件
            indent = '  ' * (len(parts) - 1)
            lines.append(f"{indent}{parts[-1]}")

        # 如果太长，截断
        if len(lines) > 80:
            lines = lines[:80]
            lines.append(f"  ... (共 {len(tree)} 个文件，已截断)")

        return '\n'.join(lines)


if __name__ == '__main__':
    tool = GitHubRepoFetcher()
    tool.run()
