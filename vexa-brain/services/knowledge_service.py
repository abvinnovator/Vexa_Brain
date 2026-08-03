"""
Knowledge Service — OKF-based smart retrieval engine with Neo4j Graph DB backend.

Reads structured Markdown files with YAML frontmatter on initial boot,
persists all learned knowledge into Neo4j Graph Database, and returns
ONLY the knowledge nodes relevant to the current user query.

Token budget: ~200-400 tokens per request (vs ~2000+ before).
"""

import os
import re
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from services import neo4j_service

logger = logging.getLogger(__name__)

# Base path for knowledge files — relative to vexa-brain/
KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "knowledge"

# Maximum tokens worth of knowledge to inject per request
# Roughly 1 token ≈ 4 chars, so 400 tokens ≈ 1600 chars
MAX_CONTEXT_CHARS = 1600

# Tag-to-file mapping — built on startup from frontmatter
_tag_index: Dict[str, List[str]] = {}
_node_cache: Dict[str, dict] = {}  # rel_path -> {frontmatter, content, path}


def init():
    """Synchronous init fallback for local file loading."""
    _load_from_files()


async def init_async():
    """Initialize knowledge service with Neo4j Graph Database support."""
    global _tag_index, _node_cache
    _tag_index = {}
    _node_cache = {}

    await neo4j_service.connect()

    if neo4j_service.is_connected():
        # Seed Neo4j from local files if empty
        if KNOWLEDGE_BASE_DIR.exists():
            await neo4j_service.seed_from_markdown_if_empty(KNOWLEDGE_BASE_DIR)

        # Load from Neo4j Graph DB
        nodes = await neo4j_service.fetch_all_nodes()
        logger.info(f"Knowledge service: loading {len(nodes)} OKF nodes from Neo4j Graph DB")

        for n in nodes:
            rel_path = n.get("path") or f"{n.get('domain')}/{n.get('filename')}.md"
            tags = n.get("tags") or [n.get("domain"), n.get("filename")]

            frontmatter = {
                "title": n.get("title") or rel_path,
                "type": n.get("type", "knowledge"),
                "confidence": n.get("confidence", 0.9),
                "last_updated": n.get("last_updated", ""),
                "status": n.get("status", "stable"),
                "tags": tags
            }

            _node_cache[rel_path] = {
                "frontmatter": frontmatter,
                "content": n.get("content", ""),
                "path": KNOWLEDGE_BASE_DIR / rel_path
            }

            # Index tags
            for tag in tags:
                if tag:
                    tag_lower = tag.lower()
                    if tag_lower not in _tag_index:
                        _tag_index[tag_lower] = []
                    if rel_path not in _tag_index[tag_lower]:
                        _tag_index[tag_lower].append(rel_path)

            # Index title words
            title = frontmatter.get("title", "")
            for word in title.lower().split():
                word = re.sub(r'[^a-z0-9]', '', word)
                if len(word) > 2:
                    if word not in _tag_index:
                        _tag_index[word] = []
                    if rel_path not in _tag_index[word]:
                        _tag_index[word].append(rel_path)

        logger.info(f"Knowledge service (Neo4j): indexed {len(_node_cache)} nodes, {len(_tag_index)} tags")
    else:
        logger.warning("Neo4j not connected. Falling back to local filesystem OKF files.")
        _load_from_files()


def _load_from_files():
    global _tag_index, _node_cache
    _tag_index = {}
    _node_cache = {}

    if not KNOWLEDGE_BASE_DIR.exists():
        logger.warning(f"Knowledge base directory not found: {KNOWLEDGE_BASE_DIR}")
        return

    md_files = list(KNOWLEDGE_BASE_DIR.rglob("*.md"))
    logger.info(f"Knowledge service (Filesystem): indexing {len(md_files)} OKF nodes")

    for md_file in md_files:
        if md_file.name == "index.md":
            continue
        try:
            frontmatter, content = _parse_okf_file(md_file)
            rel_path = str(md_file.relative_to(KNOWLEDGE_BASE_DIR)).replace("\\", "/")
            _node_cache[rel_path] = {
                "frontmatter": frontmatter,
                "content": content,
                "path": md_file
            }

            # Index by tags
            tags = frontmatter.get("tags", [])
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in _tag_index:
                    _tag_index[tag_lower] = []
                _tag_index[tag_lower].append(rel_path)

            # Also index by title words
            title = frontmatter.get("title", "")
            for word in title.lower().split():
                word = re.sub(r'[^a-z0-9]', '', word)
                if len(word) > 2:
                    if word not in _tag_index:
                        _tag_index[word] = []
                    _tag_index[word].append(rel_path)

        except Exception as e:
            logger.warning(f"Failed to parse OKF node {md_file}: {e}")

    logger.info(f"Knowledge service (Filesystem): indexed {len(_node_cache)} nodes, {len(_tag_index)} tags")


def _parse_okf_file(filepath: Path) -> Tuple[dict, str]:
    """Parse a Markdown file with YAML frontmatter. Returns (frontmatter_dict, body_content)."""
    text = filepath.read_text(encoding="utf-8")

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            content = parts[2].strip()
            return frontmatter, content

    return {}, text.strip()


async def query_relevant(user_prompt: str, user_id: str = "") -> str:
    """
    Given a user message, return ONLY the relevant knowledge context.
    """
    if not _node_cache:
        await init_async()

    if not _node_cache:
        return "No knowledge base available."

    # Extract keywords from user prompt
    keywords = _extract_keywords(user_prompt)

    # Score each node by relevance
    scores: Dict[str, float] = {}
    for keyword in keywords:
        if keyword in _tag_index:
            for node_path in _tag_index[keyword]:
                scores[node_path] = scores.get(node_path, 0) + 2.0

        for tag, paths in _tag_index.items():
            if tag.startswith(keyword) or keyword.startswith(tag):
                for node_path in paths:
                    scores[node_path] = scores.get(node_path, 0) + 1.0

    for node_path, node_data in _node_cache.items():
        content_lower = node_data["content"].lower()
        for keyword in keywords:
            if keyword in content_lower:
                scores[node_path] = scores.get(node_path, 0) + 0.5

    if not scores:
        return _get_identity_summary()

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    context_parts = []
    total_chars = 0

    for node_path, score in ranked:
        node = _node_cache[node_path]
        content = node["content"]

        if len(content) > 600:
            content = content[:600] + "..."

        if total_chars + len(content) > MAX_CONTEXT_CHARS:
            break

        title = node["frontmatter"].get("title", node_path)
        context_parts.append(f"[{title}]\n{content}")
        total_chars += len(content)

    if not context_parts:
        return _get_identity_summary()

    return "\n\n".join(context_parts)


async def get_communication_profile() -> str:
    """Return a compact communication style profile for the LLM."""
    speech_path = "speech/profile.md"
    if speech_path in _node_cache:
        content = _node_cache[speech_path]["content"]
        if len(content) > 400:
            return content[:400] + "..."
        return content

    return "No speech profile available yet. Learn from conversations."


def get_node_content(domain: str, filename: str) -> Optional[str]:
    """Get the full content of a specific knowledge node."""
    rel_path = f"{domain}/{filename}.md"
    if rel_path in _node_cache:
        return _node_cache[rel_path]["content"]
    return None


async def update_node(domain: str, filename: str, new_content: str, merge: bool = True):
    """
    Update a knowledge node with new content.
    Persists to Neo4j Graph DB and updates local file if possible.
    """
    rel_path = f"{domain}/{filename}.md"
    filepath = KNOWLEDGE_BASE_DIR / domain / f"{filename}.md"

    frontmatter = {}
    updated_content = new_content

    if rel_path in _node_cache and merge:
        existing = _node_cache[rel_path]
        frontmatter = dict(existing.get("frontmatter", {}))
        existing_content = existing.get("content", "")

        existing_lines = set(existing_content.lower().split("\n"))
        new_lines = []
        for line in new_content.split("\n"):
            if line.strip() and line.lower().strip() not in existing_lines:
                new_lines.append(line)

        if not new_lines:
            return  # Nothing new

        updated_content = existing_content + "\n" + "\n".join(new_lines)
    else:
        frontmatter = {
            "type": "knowledge",
            "title": f"{domain}/{filename}",
            "tags": [domain, filename],
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "confidence": 0.9,
            "status": "stable"
        }

    frontmatter["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    # 1. Try writing to local file (if disk is writable)
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        _write_okf_file(filepath, frontmatter, updated_content)
    except Exception as e:
        logger.warning(f"Could not write local OKF file {filepath} (ephemeral storage): {e}")

    # 2. Update memory cache
    _node_cache[rel_path] = {
        "frontmatter": frontmatter,
        "content": updated_content,
        "path": filepath
    }

    # Re-index tags
    tags = frontmatter.get("tags", [domain, filename])
    for tag in tags:
        if tag:
            tag_lower = tag.lower()
            if tag_lower not in _tag_index:
                _tag_index[tag_lower] = []
            if rel_path not in _tag_index[tag_lower]:
                _tag_index[tag_lower].append(rel_path)

    # 3. Persist to Neo4j Graph DB
    if neo4j_service.is_connected():
        await neo4j_service.upsert_node(
            domain=domain,
            filename=filename,
            title=frontmatter.get("title", f"{domain}/{filename}"),
            node_type=frontmatter.get("type", "knowledge"),
            tags=tags,
            confidence=float(frontmatter.get("confidence", 0.9)),
            last_updated=frontmatter.get("last_updated", datetime.now().strftime("%Y-%m-%d")),
            status=frontmatter.get("status", "stable"),
            content=updated_content
        )

    logger.info(f"Knowledge node updated and persisted: {rel_path}")


def _write_okf_file(filepath: Path, frontmatter: dict, content: str):
    """Write an OKF file with YAML frontmatter."""
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True).strip()
    full_content = f"---\n{fm_str}\n---\n\n{content}"
    filepath.write_text(full_content, encoding="utf-8")


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from user text for tag matching."""
    stop_words = {
        "i", "me", "my", "we", "you", "your", "the", "a", "an", "is", "are",
        "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
        "did", "will", "would", "could", "should", "may", "might", "can",
        "to", "of", "in", "for", "on", "at", "by", "from", "with", "about",
        "as", "into", "through", "during", "before", "after", "above", "below",
        "and", "but", "or", "not", "no", "so", "if", "then", "than", "that",
        "this", "these", "those", "it", "its", "what", "which", "who", "when",
        "where", "how", "why", "all", "each", "every", "some", "any", "most",
        "just", "also", "very", "really", "much", "more", "like", "want",
        "need", "please", "hey", "hi", "hello", "ok", "okay", "thanks",
        "tell", "show", "get", "give", "make", "let", "know", "think", "see",
    }

    words = re.findall(r'[a-z0-9]+', text.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 2]

    for i in range(len(words) - 1):
        bigram = f"{words[i]}_{words[i+1]}"
        if words[i] not in stop_words and words[i+1] not in stop_words:
            keywords.append(bigram)

    return keywords[:15]


def _get_identity_summary() -> str:
    """Return a minimal identity summary when no specific match is found."""
    parts = []
    for key in ["identity/personal.md", "identity/professional.md"]:
        if key in _node_cache:
            content = _node_cache[key]["content"]
            parts.append(content[:300])

    if parts:
        return "\n\n".join(parts)

    return "User: Brahma Vamsi. AI assistant: Vexa."


def get_all_tags() -> List[str]:
    return sorted(_tag_index.keys())


def get_stats() -> dict:
    return {
        "total_nodes": len(_node_cache),
        "total_tags": len(_tag_index),
        "domains": list(set(p.split("/")[0] for p in _node_cache.keys())),
        "total_content_chars": sum(len(n["content"]) for n in _node_cache.values()),
        "neo4j_connected": neo4j_service.is_connected()
    }
