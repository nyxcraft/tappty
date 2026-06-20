#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import unicodedata
from html import escape
from pathlib import Path

try:
    from markdown_it import MarkdownIt
except ImportError as exc:  # pragma: no cover - human setup path
    raise SystemExit(
        "markdown-it-py is required to build the docs site.\n"
        "Install it with: python3.12 -m pip install -r tools/requirements-docs.txt"
    ) from exc


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "gh-pages"          # build machinery: site.json, templates/, assets/
OUTPUT_DIR = ROOT / "gh-pages" / "public"  # built site (gitignored; published by Actions)
HEADER_LOGO = "assets/logo-tappty.svg"


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "section"


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def render_template(path: Path, context: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in context.items():
        text = text.replace(f"{{{{ {key} }}}}", value)
    return text


def relative_href(from_file: Path, to_file: Path) -> str:
    return os.path.relpath(to_file, from_file.parent).replace(os.sep, "/")


class MarkdownRenderer:
    def __init__(self) -> None:
        self.md = MarkdownIt("commonmark", {"html": True, "typographer": True})
        self.md.enable("table")
        self.md.enable("strikethrough")

    def render(self, text: str) -> dict[str, object]:
        tokens = self.md.parse(text)
        slug_counts: dict[str, int] = {}
        toc: list[dict[str, object]] = []
        title = None
        first_h1_index = None

        for index, token in enumerate(tokens):
            if token.type != "heading_open":
                continue
            level = int(token.tag[1])
            if index + 1 >= len(tokens):
                continue
            inline = tokens[index + 1]
            if inline.type != "inline":
                continue
            heading_text = inline.content.strip()
            if not heading_text:
                continue

            base_slug = slugify(heading_text)
            count = slug_counts.get(base_slug, 0)
            slug_counts[base_slug] = count + 1
            anchor = base_slug if count == 0 else f"{base_slug}-{count + 1}"
            token.attrSet("id", anchor)

            if level == 1 and title is None:
                title = heading_text
                first_h1_index = index
            elif level in (2, 3):
                toc.append({"level": level, "anchor": anchor, "text": heading_text})

        if first_h1_index is not None:
            del tokens[first_h1_index:first_h1_index + 3]

        html = self.md.renderer.render(tokens, self.md.options, {})
        return {"title": title, "toc": toc, "html": html}


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree(source: Path, destination: Path) -> None:
    if source.exists():
        shutil.copytree(source, destination, dirs_exist_ok=True)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def rewrite_md_links(html: str, current_output: Path, output_dir: Path,
                     basename_to_output: dict[str, str]) -> str:
    """Rewrite `<a href="...md">` links so cross-document links work in the built site too.

    The Markdown sources use ordinary relative `.md` links (e.g. `[DESIGN.md](DESIGN.md)`) so
    they also resolve when browsed on GitHub. Here we map each `.md` target -- by basename --
    to the corresponding page's pretty URL, made relative to the page being written, preserving
    any `#anchor`. Links to `.md` files that aren't site pages are left untouched."""
    def replace(match: re.Match[str]) -> str:
        href = match.group(1)
        if "://" in href or href.startswith(("#", "mailto:")):
            return match.group(0)
        path, _, anchor = href.partition("#")
        target = basename_to_output.get(os.path.basename(path).lower())
        if target is None:
            return match.group(0)
        suffix = "#" + anchor if anchor else ""
        rel = relative_href(current_output, output_dir / target)
        return f'href="{escape(rel + suffix)}"'

    return re.sub(r'href="([^"]+\.md(?:#[^"]*)?)"', replace, html)


def build_docs_nav(
    pages: list[dict[str, str]],
    current_slug: str,
    current_output: Path,
    output_dir: Path,
) -> str:
    items = []
    for page in pages:
        classes = "docs-nav__item"
        if page["slug"] == current_slug:
            classes += " is-active"
        href = relative_href(current_output, output_dir / page["output"])
        items.append(
            "\n".join(
                [
                    f'<a class="{classes}" href="{escape(href)}">',
                    f'  <span class="docs-nav__title">{escape(page["title"])}</span>',
                    f'  <span class="docs-nav__summary">{escape(page["summary"])}</span>',
                    "</a>",
                ]
            )
        )
    return "\n".join(items)


def build_toc(entries: list[dict[str, object]]) -> str:
    if not entries:
        return ""
    items = []
    for entry in entries:
        level = int(entry["level"])
        classes = f"toc__item toc__item--level-{level}"
        items.append(
            f'<li class="{classes}"><a href="#{escape(str(entry["anchor"]))}">'
            f"{escape(str(entry['text']))}</a></li>"
        )
    return (
        '<section class="toc">\n'
        '  <h2 class="toc__heading">On this page</h2>\n'
        '  <ul class="toc__list">\n'
        f"{chr(10).join(items)}\n"
        "  </ul>\n"
        "</section>"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the a11y-catscan docs site.")
    parser.add_argument("--output", default=str(OUTPUT_DIR), help="Build output directory")
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    config = read_json(SOURCE_DIR / "site.json")
    renderer = MarkdownRenderer()

    ensure_clean_dir(output_dir)
    copy_tree(SOURCE_DIR / "assets", output_dir / "assets")
    write_text(output_dir / ".nojekyll", "")

    docs_pages: list[dict[str, str]] = []
    for entry in config["docs"]:
        docs_pages.append(
            {
                "slug": entry["slug"],
                "title": entry["title"],
                "summary": entry["summary"],
                "source": entry["source"],
                "output": str(Path(entry["slug"]) / "index.html"),
                "featured": bool(entry.get("featured", False)),
            }
        )

    for page in docs_pages:
        page["href"] = page["output"].replace(os.sep, "/")

    # Map each source's basename -> its built page, so cross-document `.md` links get rewritten
    # to pretty URLs. README isn't a page of its own; point links to it at the home page.
    basename_to_output = {os.path.basename(p["source"]).lower(): p["output"] for p in docs_pages}
    basename_to_output.setdefault("readme.md", "index.html")

    featured_pages = [page for page in docs_pages if page["featured"]] or docs_pages
    docs_cards = []
    for page in featured_pages:
        docs_cards.append(
            "\n".join(
                [
                    '<article class="doc-card">',
                    f'  <h3><a href="{escape(page["href"])}">{escape(page["title"])}</a></h3>',
                    f'  <p>{escape(page["summary"])}</p>',
                    f'  <a class="doc-card__link" href="{escape(page["href"])}">Open</a>',
                    "</article>",
                ]
            )
        )

    hero_primary = docs_pages[0]["href"] if docs_pages else "#"
    hero_secondary = docs_pages[1]["href"] if len(docs_pages) > 1 else hero_primary
    github_href = config.get("github_href", "#")

    home_html = render_template(
        SOURCE_DIR / "templates" / "home.html",
        {
            "site_name": escape(config["site_name"]),
            "site_tagline": escape(config["site_tagline"]),
            "site_description": escape(config["site_description"]),
            "logo_href": escape(HEADER_LOGO),
            "github_href": escape(github_href),
            "docs_href": escape(hero_primary),
            "primary_href": escape(hero_primary),
            "secondary_href": escape(hero_secondary),
            "docs_cards": "\n".join(docs_cards),
        },
    )
    write_text(output_dir / "index.html", home_html)

    for page in docs_pages:
        source_path = ROOT / page["source"]
        rendered = renderer.render(source_path.read_text(encoding="utf-8"))
        output_path = output_dir / page["output"]
        content_html = rewrite_md_links(
            str(rendered["html"]), output_path, output_dir, basename_to_output
        )
        nav_html = build_docs_nav(docs_pages, page["slug"], output_path, output_dir)
        toc_html = build_toc(rendered["toc"])  # type: ignore[arg-type]
        asset_href = relative_href(output_path, output_dir / "assets" / "site.css")
        logo_href = relative_href(output_path, output_dir / HEADER_LOGO)
        home_href = relative_href(output_path, output_dir / "index.html")
        docs_href = relative_href(output_path, output_dir / docs_pages[0]["output"])

        doc_html = render_template(
            SOURCE_DIR / "templates" / "doc.html",
            {
                "page_title": escape(page["title"]),
                "site_name": escape(config["site_name"]),
                "site_tagline": escape(config["site_tagline"]),
                "page_summary": escape(page["summary"]),
                "assets_href": escape(asset_href),
                "logo_href": escape(logo_href),
                "home_href": escape(home_href),
                "github_href": escape(github_href),
                "docs_href": escape(docs_href),
                "docs_nav": nav_html,
                "toc": toc_html,
                "source_title": escape(str(rendered["title"] or "")),
                "content": content_html,
            },
        )
        write_text(output_path, doc_html)

    print(f"Built site into {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
