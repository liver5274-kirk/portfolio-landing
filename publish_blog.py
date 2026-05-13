#!/usr/bin/env python3
"""
Obsidian Vault → GitHub Pages Blog 發布管道

用法：
  # 發布一篇 vault 筆記（路徑相對於 vault root）
  python publish_blog.py "nvidia-omniverse/01-openusd-fundamentals.md"

  # 從 vault 外部的任意 markdown 發布
  python publish_blog.py --file /path/to/post.md --title "標題" --date 2026-05-10

  # 只重建 blog/index.html（不改文章）
  python publish_blog.py --index-only

  # 預覽模式：只印出 HTML，不寫入檔案
  python publish_blog.py "nvidia-omniverse/01-openusd-fundamentals.md" --dry-run
"""

import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, date

# ─── 設定 ─────────────────────────────────────────────
_raw = os.environ.get("OBSIDIAN_VAULT_PATH", "/mnt/c/ObsidianVault")
VAULT_PATH = os.path.expandvars(os.path.expanduser(_raw))
REPO_ROOT = Path(__file__).resolve().parent
POSTS_DIR = REPO_ROOT / "blog" / "posts"
INDEX_PATH = REPO_ROOT / "blog" / "index.html"
SITE_URL = "https://liver5274-kirk.github.io/portfolio-landing"


# ─── Markdown → HTML 轉換器 ───────────────────────────

def obsidian_to_html(md_text: str) -> str:
    """將 Obsidian-flavored markdown 轉換為 HTML。"""

    lines = md_text.split("\n")
    html_lines = []
    in_code_block = False
    code_lang = ""
    code_buffer = []
    in_list = False
    list_type = None  # 'ul' or 'ol'
    in_blockquote = False
    in_callout = False
    callout_type = ""
    callout_title = ""

    def flush_list():
        nonlocal in_list, list_type
        if in_list:
            tag = list_type or "ul"
            html_lines.append(f"</{tag}>")
            in_list = False
            list_type = None

    def flush_code():
        nonlocal in_code_block, code_buffer, code_lang
        if in_code_block:
            lang_attr = f' class="language-{code_lang}"' if code_lang else ""
            code_text = "\n".join(code_buffer)
            # escape HTML in code
            code_text = code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_lines.append(f'<pre><code{lang_attr}>{code_text}</code></pre>')
            code_buffer = []
            code_lang = ""
            in_code_block = False

    def flush_blockquote():
        nonlocal in_blockquote, in_callout
        if in_blockquote:
            if in_callout:
                html_lines.append("</div>")
                in_callout = False
            html_lines.append("</blockquote>")
            in_blockquote = False

    i = 0
    while i < len(lines):
        line = lines[i]

        # 跳過 frontmatter
        if i == 0 and line.strip() == "---":
            i += 1
            while i < len(lines) and lines[i].strip() != "---":
                i += 1
            i += 1  # skip closing ---
            continue

        # Code block toggle
        if line.strip().startswith("```"):
            if not in_code_block:
                flush_list()
                flush_blockquote()
                in_code_block = True
                code_lang = line.strip()[3:].strip()
            else:
                flush_code()
            i += 1
            continue

        if in_code_block:
            code_buffer.append(line)
            i += 1
            continue

        # Blockquote / Callout
        if line.startswith(">"):
            if not in_blockquote:
                flush_list()
                in_blockquote = True
                # Check for callout: > [!note] or > [!warning] etc.
                callout_match = re.match(r'^>\s*\[!(\w+)\]\s*(.*)', line)
                if callout_match:
                    in_callout = True
                    callout_type = callout_match.group(1).lower()
                    callout_title = callout_match.group(2).strip() or callout_type.capitalize()
                    icon_map = {"note": "📝", "warning": "⚠️", "tip": "💡", "info": "ℹ️",
                                "danger": "🔥", "example": "📋", "quote": "💬"}
                    icon = icon_map.get(callout_type, "📌")
                    html_lines.append(f'<blockquote class="callout callout-{callout_type}">')
                    html_lines.append(f'<div class="callout-header">{icon} <strong>{callout_title}</strong></div>')
                    html_lines.append('<div class="callout-body">')
                else:
                    html_lines.append("<blockquote>")
            else:
                # Inside existing blockquote
                if in_callout:
                    content = line[1:].strip()
                    if content:
                        html_lines.append(f"<p>{inline_md(content)}</p>")
                else:
                    content = line[1:].strip()
                    if content:
                        html_lines.append(f"<p>{inline_md(content)}</p>")
            i += 1
            # Peek ahead: if next line is not '>', close blockquote
            if i >= len(lines) or not lines[i].startswith(">"):
                flush_blockquote()
            continue

        # Horizontal rule
        if line.strip() in ("---", "***", "___", "- - -"):
            flush_list()
            flush_blockquote()
            html_lines.append("<hr>")
            i += 1
            continue

        # Empty line
        if not line.strip():
            flush_list()
            flush_blockquote()
            i += 1
            continue

        # Headers
        header_match = re.match(r'^(#{1,6})\s+(.+?)(?:\s+#+)?$', line)
        if header_match:
            flush_list()
            flush_blockquote()
            level = len(header_match.group(1))
            text = inline_md(header_match.group(2))
            html_lines.append(f"<h{level}>{text}</h{level}>")
            i += 1
            continue

        # Unordered list
        ul_match = re.match(r'^(\s*)[-*+]\s+(.+)', line)
        if ul_match:
            flush_blockquote()
            if not in_list or list_type != "ul":
                flush_list()
                html_lines.append("<ul>")
                in_list = True
                list_type = "ul"
            html_lines.append(f"<li>{inline_md(ul_match.group(2))}</li>")
            i += 1
            continue

        # Ordered list
        ol_match = re.match(r'^(\s*)\d+\.\s+(.+)', line)
        if ol_match:
            flush_blockquote()
            if not in_list or list_type != "ol":
                flush_list()
                html_lines.append("<ol>")
                in_list = True
                list_type = "ol"
            html_lines.append(f"<li>{inline_md(ol_match.group(2))}</li>")
            i += 1
            continue

        # Table?
        if "|" in line and line.strip().startswith("|"):
            flush_list()
            flush_blockquote()
            table_lines = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            html_lines.append(build_table(table_lines))
            continue

        # Regular paragraph
        flush_list()
        flush_blockquote()
        html_lines.append(f"<p>{inline_md(line)}</p>")
        i += 1

    # Flush any remaining state
    flush_code()
    flush_list()
    flush_blockquote()

    return "\n".join(html_lines)


def inline_md(text: str) -> str:
    """處理行內 markdown：粗體、斜體、行內程式碼、連結、圖片、wikilinks。"""
    # Inline code (must come before bold/italic to avoid conflicts with * in code)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # Bold + Italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # Images ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1" loading="lazy">', text)
    # Links [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    # Wikilinks [[Page]] or [[Page|Display]]
    text = re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', lambda m: m.group(2) or m.group(1), text)
    return text


def build_table(lines: list) -> str:
    """將 markdown 表格行轉為 HTML table。"""
    if len(lines) < 2:
        return ""
    # Parse header
    headers = [c.strip() for c in lines[0].strip("|").split("|")]
    # Skip separator line (|---|---|)
    rows = []
    for line in lines[2:]:
        cells = [inline_md(c.strip()) for c in line.strip("|").split("|")]
        rows.append(cells)

    html = ["<table>"]
    html.append("<thead><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead>")
    html.append("<tbody>")
    for row in rows:
        html.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    html.append("</tbody></table>")
    return "\n".join(html)


# ─── Frontmatter 解析 ──────────────────────────────────

def parse_frontmatter(text: str) -> tuple:
    """解析 YAML frontmatter，回傳 (metadata_dict, body_text)。"""
    meta = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    # Parse tags as list
                    if key == "tags" and val.startswith("[") and val.endswith("]"):
                        val = [t.strip().strip('"').strip("'") for t in val[1:-1].split(",")]
                    meta[key] = val
            body = parts[2]
    return meta, body


# ─── 部落格文章 HTML 模板 ──────────────────────────────

def blog_post_html(title: str, date_str: str, tags: list, body_html: str, slug: str) -> str:
    """產生單篇文章的完整 HTML。"""
    tags_html = ""
    if tags:
        tags_html = "".join(
            f'<span class="tag">{t}</span>' for t in tags
        )

    return f'''<!DOCTYPE html>
<html lang="zh-TW" class="scroll-smooth">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — Kirk.dev 技術部落格</title>
  <meta name="description" content="{title} — Kirk 的技術筆記與開發心得。全端開發、AI 自動化、量化交易、3D 圖學。">
  <meta property="og:title" content="{title}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="{SITE_URL}/blog/posts/{slug}.html">
  <link rel="canonical" href="{SITE_URL}/blog/posts/{slug}.html">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          colors: {{
            brand: {{ 50: '#eefbf3', 100: '#d6f5e0', 200: '#b0eac5', 300: '#7cd9a2', 400: '#47c07b', 500: '#22a55e', 600: '#148549', 700: '#116a3d', 800: '#105433', 900: '#0e452c', 950: '#072615' }},
            surface: {{ 50: '#f8fafc', 100: '#f1f5f9', 200: '#e2e8f0', 300: '#cbd5e1', 700: '#334155', 800: '#1e293b', 850: '#172033', 900: '#0f172a', 950: '#020617' }}
          }}
        }}
      }}
    }}
  </script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
  <style>
    /* ── 文章內容排版 ── */
    .prose {{ max-width: 65ch; }}
    .prose h1 {{ font-size: 2rem; font-weight: 800; margin-top: 2rem; margin-bottom: 0.75rem; color: #e2e8f0; }}
    .prose h2 {{ font-size: 1.5rem; font-weight: 700; margin-top: 2rem; margin-bottom: 0.5rem; color: #e2e8f0; border-bottom: 1px solid #1e293b; padding-bottom: 0.25rem; }}
    .prose h3 {{ font-size: 1.2rem; font-weight: 600; margin-top: 1.5rem; margin-bottom: 0.5rem; color: #cbd5e1; }}
    .prose p {{ margin-bottom: 1rem; line-height: 1.75; color: #94a3b8; }}
    .prose a {{ color: #47c07b; text-decoration: underline; text-underline-offset: 2px; }}
    .prose a:hover {{ color: #7cd9a2; }}
    .prose strong {{ color: #e2e8f0; font-weight: 600; }}
    .prose code {{ background: #1e293b; color: #7cd9a2; padding: 0.15em 0.4em; border-radius: 4px; font-size: 0.9em; font-family: 'JetBrains Mono', 'Fira Code', monospace; }}
    .prose pre {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 1rem 1.25rem; overflow-x: auto; margin: 1rem 0; }}
    .prose pre code {{ background: none; color: #cbd5e1; padding: 0; font-size: 0.85rem; line-height: 1.6; }}
    .prose ul, .prose ol {{ margin: 0.75rem 0; padding-left: 1.5rem; color: #94a3b8; }}
    .prose li {{ margin-bottom: 0.35rem; line-height: 1.65; }}
    .prose blockquote {{ border-left: 3px solid #22a55e; padding: 0.75rem 1rem; margin: 1rem 0; background: rgba(34,165,94,0.05); border-radius: 0 6px 6px 0; }}
    .prose blockquote p {{ color: #94a3b8; margin: 0; }}
    .prose hr {{ border: none; border-top: 1px solid #1e293b; margin: 2rem 0; }}
    .prose table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.9rem; }}
    .prose th {{ background: #1e293b; color: #e2e8f0; padding: 0.5rem 0.75rem; text-align: left; font-weight: 600; border: 1px solid #334155; }}
    .prose td {{ padding: 0.5rem 0.75rem; border: 1px solid #1e293b; color: #94a3b8; }}
    .prose img {{ max-width: 100%; border-radius: 8px; margin: 1rem 0; }}
    /* ── Callout ── */
    .callout {{ border-left-width: 3px; padding: 0.75rem 1rem; margin: 1rem 0; border-radius: 0 8px 8px 0; }}
    .callout-note {{ background: rgba(59,130,246,0.08); border-color: #3b82f6; }}
    .callout-warning {{ background: rgba(245,158,11,0.08); border-color: #f59e0b; }}
    .callout-tip {{ background: rgba(34,197,94,0.08); border-color: #22c55e; }}
    .callout-info {{ background: rgba(6,182,212,0.08); border-color: #06b6d4; }}
    .callout-danger {{ background: rgba(239,68,68,0.08); border-color: #ef4444; }}
    .callout-example {{ background: rgba(139,92,246,0.08); border-color: #8b5cf6; }}
    .callout-header {{ font-weight: 600; margin-bottom: 0.35rem; color: #cbd5e1; }}
    .callout-body p {{ margin: 0; }}
    /* ── Tags ── */
    .tag {{ display: inline-block; padding: 0.15em 0.6em; font-size: 0.75rem; background: #0f172a; color: #47c07b; border: 1px solid #1e293b; border-radius: 999px; margin-right: 0.35rem; }}
    /* ── Back link ── */
    .back-link {{ color: #64748b; font-size: 0.85rem; }}
    .back-link:hover {{ color: #47c07b; }}
  </style>
</head>
<body class="bg-surface-950 text-slate-200 font-sans antialiased">

<!-- NAV -->
<nav class="fixed top-0 w-full z-50 bg-surface-950/80 backdrop-blur-md border-b border-slate-800">
  <div class="max-w-6xl mx-auto px-6 py-4 flex justify-between items-center">
    <a href="{SITE_URL}/" class="text-brand-400 font-bold text-lg tracking-tight no-underline">Kirk<span class="text-slate-400 font-normal">.dev</span></a>
    <div class="hidden md:flex gap-8 text-sm text-slate-400">
      <a href="{SITE_URL}/#works" class="hover:text-brand-400 transition no-underline">作品</a>
      <a href="{SITE_URL}/#skills" class="hover:text-brand-400 transition no-underline">技能</a>
      <a href="{SITE_URL}/blog/" class="text-brand-400 transition no-underline">部落格</a>
      <a href="{SITE_URL}/#contact" class="hover:text-brand-400 transition no-underline">聯繫</a>
    </div>
  </div>
</nav>

<!-- ARTICLE -->
<article class="pt-28 pb-20 px-6 max-w-3xl mx-auto">
  <header class="mb-10">
    <a href="{SITE_URL}/blog/" class="back-link mb-4 inline-block">← 所有文章</a>
    <h1 class="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-100 mb-3">{title}</h1>
    <div class="flex items-center gap-4 text-sm text-slate-500">
      <span>{date_str}</span>
      <span>·</span>
      <span>Kirk</span>
    </div>
    <div class="mt-3">{tags_html}</div>
  </header>

  <div class="prose">
{body_html}
  </div>

  <footer class="mt-16 pt-8 border-t border-slate-800 text-sm text-slate-600 space-y-2">
    <p>© {date_str[:4]} Kirk — 全端開發 × AI 自動化</p>
    <p>有專案想法？<a href="{SITE_URL}/#contact" class="text-brand-400">聯絡我</a></p>
  </footer>
</article>

</body>
</html>'''


# ─── Blog 列表頁 HTML 模板 ─────────────────────────────

def blog_index_html(posts: list) -> str:
    """產生 blog/index.html 列表頁。posts = [{title, date_str, slug, tags, excerpt}, ...]"""
    posts_html = ""
    for p in posts:
        tags_html = ""
        if p.get("tags"):
            tags_html = "".join(f'<span class="tag">{t}</span>' for t in p["tags"])
        excerpt = p.get("excerpt", "")
        posts_html += f'''
    <article class="bg-surface-900 rounded-xl border border-slate-800 hover:border-brand-700 transition p-6 space-y-3">
      <div class="flex items-center gap-4 text-xs text-slate-500">
        <span>{p["date_str"]}</span>
        <div>{tags_html}</div>
      </div>
      <h2 class="text-xl font-bold">
        <a href="{SITE_URL}/blog/posts/{p["slug"]}.html" class="text-slate-100 hover:text-brand-400 transition no-underline">{p["title"]}</a>
      </h2>
      <p class="text-sm text-slate-400 leading-relaxed">{excerpt}</p>
      <a href="{SITE_URL}/blog/posts/{p["slug"]}.html" class="text-brand-400 text-sm font-medium hover:text-brand-300 transition no-underline">閱讀全文 →</a>
    </article>'''

    return f'''<!DOCTYPE html>
<html lang="zh-TW" class="scroll-smooth">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>技術部落格 — Kirk.dev</title>
  <meta name="description" content="Kirk 的技術筆記：全端開發、AI 自動化、量化交易、3D 圖學。實戰導向的開發心得。">
  <meta property="og:title" content="技術部落格 — Kirk.dev">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{SITE_URL}/blog/">
  <link rel="canonical" href="{SITE_URL}/blog/">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          colors: {{
            brand: {{ 50: '#eefbf3', 100: '#d6f5e0', 200: '#b0eac5', 300: '#7cd9a2', 400: '#47c07b', 500: '#22a55e', 600: '#148549', 700: '#116a3d', 800: '#105433', 900: '#0e452c', 950: '#072615' }},
            surface: {{ 50: '#f8fafc', 100: '#f1f5f9', 200: '#e2e8f0', 300: '#cbd5e1', 700: '#334155', 800: '#1e293b', 850: '#172033', 900: '#0f172a', 950: '#020617' }}
          }}
        }}
      }}
    }}
  </script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
  <style>
    .tag {{ display: inline-block; padding: 0.15em 0.6em; font-size: 0.7rem; background: #0f172a; color: #47c07b; border: 1px solid #1e293b; border-radius: 999px; margin-right: 0.25rem; }}
  </style>
</head>
<body class="bg-surface-950 text-slate-200 font-sans antialiased">

<!-- NAV -->
<nav class="fixed top-0 w-full z-50 bg-surface-950/80 backdrop-blur-md border-b border-slate-800">
  <div class="max-w-6xl mx-auto px-6 py-4 flex justify-between items-center">
    <a href="{SITE_URL}/" class="text-brand-400 font-bold text-lg tracking-tight no-underline">Kirk<span class="text-slate-400 font-normal">.dev</span></a>
    <div class="hidden md:flex gap-8 text-sm text-slate-400">
      <a href="{SITE_URL}/#works" class="hover:text-brand-400 transition no-underline">作品</a>
      <a href="{SITE_URL}/#skills" class="hover:text-brand-400 transition no-underline">技能</a>
      <a href="{SITE_URL}/blog/" class="text-brand-400 transition no-underline">部落格</a>
      <a href="{SITE_URL}/#contact" class="hover:text-brand-400 transition no-underline">聯繫</a>
    </div>
  </div>
</nav>

<!-- HEADER -->
<section class="pt-32 pb-12 px-6 max-w-3xl mx-auto">
  <h1 class="text-4xl font-extrabold tracking-tight mb-3">技術部落格</h1>
  <p class="text-slate-400 leading-relaxed">
    全端開發 · AI 自動化 · 量化交易 · 3D 圖學<br>
    實戰導向的開發心得，不定期更新。
  </p>
</section>

<!-- POSTS -->
<section class="pb-20 px-6 max-w-3xl mx-auto space-y-6">
{posts_html}
</section>

<!-- FOOTER -->
<footer class="py-8 border-t border-slate-800 text-center text-xs text-slate-600">
  © {datetime.now().year} Kirk — 全端開發 × AI 自動化
</footer>

</body>
</html>'''


# ─── 主要邏輯 ──────────────────────────────────────────

def extract_excerpt(html: str, max_chars: int = 150) -> str:
    """從文章 HTML 提取前 N 字作為摘要（去除 HTML 標籤）。"""
    text = re.sub(r'<[^>]+>', '', html)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def get_published_posts() -> list:
    """掃描 blog/posts/ 目錄，回傳已發布文章清單。"""
    posts = []
    if not POSTS_DIR.exists():
        return posts
    for f in sorted(POSTS_DIR.glob("*.html"), reverse=True):
        # Parse metadata from HTML comments or filename
        content = f.read_text(encoding="utf-8")
        # Extract title from <title> tag
        title_match = re.search(r'<title>(.+?)(?:\s+—\s+Kirk\.dev)?</title>', content)
        title = title_match.group(1) if title_match else f.stem
        # Extract tags
        tags = re.findall(r'<span class="tag">(.+?)</span>', content)
        # Extract date from filename (YYYY-MM-DD-slug)
        date_match = re.match(r'(\d{4}-\d{2}-\d{2})', f.stem)
        date_str = date_match.group(1) if date_match else ""
        # Extract excerpt from <meta name="description">
        desc_match = re.search(r'<meta name="description" content="(.+?)"', content)
        excerpt = desc_match.group(1) if desc_match else extract_excerpt(content)

        posts.append({
            "slug": f.stem,
            "title": title,
            "date_str": date_str,
            "tags": tags,
            "excerpt": excerpt
        })
    return posts


def rebuild_index():
    """重建 blog/index.html。"""
    posts = get_published_posts()
    html = blog_index_html(posts)
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(html, encoding="utf-8")
    print(f"✅ blog/index.html 已重建（{len(posts)} 篇文章）")


def publish_vault_post(vault_path: str, dry_run: bool = False, 
                       title_override: str = None, date_override: str = None, 
                       tags_override: list = None):
    """從 Obsidian vault 發布一篇文章。"""
    full_path = Path(VAULT_PATH) / vault_path
    if not full_path.exists():
        print(f"❌ 找不到檔案：{full_path}")
        sys.exit(1)

    md_text = full_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(md_text)

    # 從 frontmatter 或 vault 路徑推導 metadata（CLI override 優先）
    title = title_override or meta.get("title", full_path.stem)
    date_str = date_override or meta.get("date", date.today().isoformat())
    tags = tags_override or meta.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    # 產生 slug：YYYY-MM-DD + 檔名（去掉數字前綴）
    stem = full_path.stem
    # Remove leading numbers like "01-" or "01_"
    stem = re.sub(r'^\d+[-_]', '', stem)
    slug = f"{date_str}-{stem}"

    # 轉換為 HTML
    body_html = obsidian_to_html(body)
    full_html = blog_post_html(title, date_str, tags, body_html, slug)

    if dry_run:
        print(f"=== DRY RUN: {title} ===")
        print(f"Slug: {slug}")
        print(f"Tags: {tags}")
        print(f"Output would be: blog/posts/{slug}.html")
        print(f"Length: {len(full_html)} chars")
        return

    # 寫入檔案
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    post_path = POSTS_DIR / f"{slug}.html"
    post_path.write_text(full_html, encoding="utf-8")
    print(f"✅ 已發布：{title}")
    print(f"   → blog/posts/{slug}.html")

    # 重建 index
    rebuild_index()


def publish_from_file(file_path: str, title: str, date_str: str, tags: list, dry_run=False):
    """從任意 markdown 檔案發布。"""
    fp = Path(file_path)
    if not fp.exists():
        print(f"❌ 找不到檔案：{file_path}")
        sys.exit(1)

    md_text = fp.read_text(encoding="utf-8")
    # Try frontmatter first
    meta, body = parse_frontmatter(md_text)
    title = meta.get("title", title)
    date_str = meta.get("date", date_str)
    tags = meta.get("tags", tags)
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    stem = fp.stem
    stem = re.sub(r'^\d+[-_]', '', stem)
    slug = f"{date_str}-{stem}"

    body_html = obsidian_to_html(body)
    full_html = blog_post_html(title, date_str, tags, body_html, slug)

    if dry_run:
        print(f"=== DRY RUN: {title} ===")
        print(f"Slug: {slug}")
        print(f"Output would be: blog/posts/{slug}.html")
        return

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    post_path = POSTS_DIR / f"{slug}.html"
    post_path.write_text(full_html, encoding="utf-8")
    print(f"✅ 已發布：{title}")
    print(f"   → blog/posts/{slug}.html")
    rebuild_index()


# ─── CLI ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Obsidian → Blog 發布工具")
    parser.add_argument("vault_path", nargs="?", help="Obsidian vault 內的筆記路徑（相對 vault root）")
    parser.add_argument("--file", "-f", help="任意 markdown 檔案路徑")
    parser.add_argument("--title", "-t", help="文章標題（--file 模式用）")
    parser.add_argument("--date", "-d", default=date.today().isoformat(), help="發布日期 (YYYY-MM-DD)")
    parser.add_argument("--tags", help="標籤，逗號分隔")
    parser.add_argument("--dry-run", "-n", action="store_true", help="預覽模式，不寫入檔案")
    parser.add_argument("--index-only", action="store_true", help="只重建 blog/index.html")
    args = parser.parse_args()

    if args.index_only:
        rebuild_index()
        return

    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []

    if args.file:
        if not args.title:
            print("❌ --file 模式需要 --title")
            sys.exit(1)
        publish_from_file(args.file, args.title, args.date, tags, args.dry_run)
    elif args.vault_path:
        publish_vault_post(args.vault_path, args.dry_run, 
                          title_override=args.title, date_override=args.date, 
                          tags_override=tags)
    else:
        parser.print_help()
        print("\n用法範例：")
        print('  python publish_blog.py "nvidia-omniverse/01-openusd-fundamentals.md"')
        print('  python publish_blog.py --file /path/to/post.md --title "我的文章" --tags "Python,AI"')
        print('  python publish_blog.py --index-only')


if __name__ == "__main__":
    main()
