from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


REQUIRED_SECTIONS = (
    "Current Responsibilities",
    "Current Implementation Map",
    "Data and Control Flow",
    "Tests and Coverage",
    "Known Gaps or Risks",
    "Optimization Backlog",
    "Follow-up Audit Questions",
)

PLACEHOLDER_RE = re.compile(r"\b(?:TBD|TODO|FIXME|placeholder)\b", re.IGNORECASE)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
BACKTICK_PATH_RE = re.compile(
    r"`((?:backend|frontend|database|docs|scripts)/[^`]+)`"
)
TRAILING_PUNCTUATION = ".,:;"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_leaf(path: Path) -> bool:
    return path.name != "README.md" and not path.name.startswith("generated-")


def _headings(text: str) -> list[str]:
    return [
        line.removeprefix("## ").strip()
        for line in text.splitlines()
        if line.startswith("## ")
    ]


def _local_doc_links(text: str) -> list[str]:
    links = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        link = match.group(1).strip()
        if link.startswith(("http://", "https://", "#")):
            continue
        links.append(link)
    return links


def _resolve_under_audit_root(audit_root: Path, link: str) -> Path | None:
    clean_link = unquote(link.split("#", 1)[0])
    if not clean_link:
        return None

    resolved_root = audit_root.resolve()
    resolved_link = (audit_root / clean_link).resolve()
    try:
        resolved_link.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved_link


def _path_exists(repo_root: Path, path_text: str) -> bool:
    clean_path = path_text.strip().rstrip(TRAILING_PUNCTUATION)
    if "*" in clean_path:
        return True
    return (repo_root / clean_path).exists()


def validate_audit_docs(audit_root: Path) -> list[str]:
    errors: list[str] = []
    repo_root = _repo_root()
    audit_root = audit_root if audit_root.is_absolute() else repo_root / audit_root
    readme_path = audit_root / "README.md"

    if not readme_path.exists():
        errors.append(f"{readme_path}: README.md is missing")
        return errors

    readme_text = readme_path.read_text(encoding="utf-8")
    for link in _local_doc_links(readme_text):
        resolved_link = _resolve_under_audit_root(audit_root, link)
        if resolved_link is None:
            errors.append(f"{readme_path}: link escapes audit root: {link}")
        elif not resolved_link.exists():
            errors.append(f"{readme_path}: link target does not exist: {link}")

    for markdown_path in sorted(audit_root.rglob("*.md")):
        text = markdown_path.read_text(encoding="utf-8")

        if PLACEHOLDER_RE.search(text):
            errors.append(f"{markdown_path}: contains placeholder text")

        if _is_leaf(markdown_path):
            headings = set(_headings(text))
            for section in REQUIRED_SECTIONS:
                if section not in headings:
                    errors.append(
                        f"{markdown_path}: missing required section: {section}"
                    )

        for match in BACKTICK_PATH_RE.finditer(text):
            code_path = match.group(1)
            if not _path_exists(repo_root, code_path):
                errors.append(
                    f"{markdown_path}: backticked path does not exist: {code_path}"
                )

    return errors


def main() -> int:
    errors = validate_audit_docs(Path("docs/audit"))
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
