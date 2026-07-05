"""
Knowledge Service — OKF-based smart retrieval engine.

Replaces the old "dump entire memory.txt into prompt" approach.
Reads structured Markdown files with YAML frontmatter, and returns
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

logger = logging.getLogger(__name__)

# Base path for knowledge files — relative to vexa-brain/
KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "knowledge"

# Maximum tokens worth of knowledge to inject per request
# Roughly 1 token ≈ 4 chars, so 400 tokens ≈ 1600 chars
MAX_CONTEXT_CHARS = 1600

# Tag-to-file mapping — built on startup from frontmatter
_tag_index: Dict[str, List[Path]] = {}
_node_cache: Dict[str, dict] = {}  # path -> {frontmatter, content}


def init():
    """Initialize the knowledge service — build tag index from all OKF nodes."""
    global _tag_index, _node_cache
    _tag_index = {}
    _node_cache = {}

    if not KNOWLEDGE_BASE_DIR.exists():
        logger.warning(f"Knowledge base directory not found: {KNOWLEDGE_BASE_DIR}")
        return

    md_files = list(KNOWLEDGE_BASE_DIR.rglob("*.md"))
    logger.info(f"Knowledge service: indexing {len(md_files)} OKF nodes")

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

    logger.info(f"Knowledge service: indexed {len(_node_cache)} nodes, {len(_tag_index)} tags")


def _parse_okf_file(filepath: Path) -> Tuple[dict, str]:
    """Parse a Markdown file with YAML frontmatter. Returns (frontmatter_dict, body_content)."""
    text = filepath.read_text(encoding="utf-8")

    # Extract YAML frontmatter between --- markers
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            content = parts[2].strip()
            return frontmatter, content

    # No frontmatter — treat entire file as content
    return {}, text.strip()


async def query_relevant(user_prompt: str, user_id: str = "") -> str:
    """
    Given a user message, return ONLY the relevant knowledge context.

    Strategy:
    1. Tokenize the user prompt into keywords
    2. Match keywords against the tag index
    3. Score and rank matching nodes
    4. Return top nodes within token budget

    Returns a compact string ready to inject into the LLM prompt.
    """
    if not _node_cache:
        init()

    if not _node_cache:
        return "No knowledge base available."

    # Extract keywords from user prompt
    keywords = _extract_keywords(user_prompt)

    # Score each node by relevance
    scores: Dict[str, float] = {}
    for keyword in keywords:
        # Exact tag match
        if keyword in _tag_index:
            for node_path in _tag_index[keyword]:
                scores[node_path] = scores.get(node_path, 0) + 2.0

        # Partial tag match (prefix)
        for tag, paths in _tag_index.items():
            if tag.startswith(keyword) or keyword.startswith(tag):
                for node_path in paths:
                    scores[node_path] = scores.get(node_path, 0) + 1.0

    # Also check content for keyword matches
    for node_path, node_data in _node_cache.items():
        content_lower = node_data["content"].lower()
        for keyword in keywords:
            if keyword in content_lower:
                scores[node_path] = scores.get(node_path, 0) + 0.5

    if not scores:
        # No specific match — return identity basics (always useful)
        return _get_identity_summary()

    # Sort by score (descending) and collect within budget
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    context_parts = []
    total_chars = 0

    for node_path, score in ranked:
        node = _node_cache[node_path]
        content = node["content"]

        # Truncate individual node if too long
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
        # Return first 400 chars — compact enough for every request
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

    If merge=True, appends to existing content (deduplicating).
    If merge=False, replaces entirely.
    """
    filepath = KNOWLEDGE_BASE_DIR / domain / f"{filename}.md"

    if filepath.exists() and merge:
        frontmatter, existing_content = _parse_okf_file(filepath)

        # Simple deduplication — don't add lines that already exist
        existing_lines = set(existing_content.lower().split("\n"))
        new_lines = []
        for line in new_content.split("\n"):
            if line.strip() and line.lower().strip() not in existing_lines:
                new_lines.append(line)

        if not new_lines:
            return  # Nothing new

        # Update timestamp
        frontmatter["last_updated"] = datetime.now().strftime("%Y-%m-%d")

        # Write back
        updated_content = existing_content + "\n" + "\n".join(new_lines)
        _write_okf_file(filepath, frontmatter, updated_content)
    else:
        # New file or full replace
        frontmatter = {
            "type": "knowledge",
            "title": f"{domain}/{filename}",
            "tags": [domain, filename],
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "confidence": 0.7,
            "source": "learned"
        }
        filepath.parent.mkdir(parents=True, exist_ok=True)
        _write_okf_file(filepath, frontmatter, new_content)

    # Refresh cache for this node
    rel_path = f"{domain}/{filename}.md"
    fm, content = _parse_okf_file(filepath)
    _node_cache[rel_path] = {
        "frontmatter": fm,
        "content": content,
        "path": filepath
    }

    # Re-index tags
    for tag in fm.get("tags", []):
        tag_lower = tag.lower()
        if tag_lower not in _tag_index:
            _tag_index[tag_lower] = []
        if rel_path not in _tag_index[tag_lower]:
            _tag_index[tag_lower].append(rel_path)

    logger.info(f"Knowledge node updated: {rel_path}")


def _write_okf_file(filepath: Path, frontmatter: dict, content: str):
    """Write an OKF file with YAML frontmatter."""
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True).strip()
    full_content = f"---\n{fm_str}\n---\n\n{content}"
    filepath.write_text(full_content, encoding="utf-8")


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from user text for tag matching."""
    # Remove common stop words
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

    # Also try bigrams for compound concepts
    for i in range(len(words) - 1):
        bigram = f"{words[i]}_{words[i+1]}"
        if words[i] not in stop_words and words[i+1] not in stop_words:
            keywords.append(bigram)

    return keywords[:15]  # Cap at 15 keywords


def _get_identity_summary() -> str:
    """Return a minimal identity summary when no specific match is found."""
    parts = []
    for key in ["identity/personal.md", "identity/professional.md"]:
        if key in _node_cache:
            content = _node_cache[key]["content"]
            # Take first 300 chars of each
            parts.append(content[:300])

    if parts:
        return "\n\n".join(parts)

    return "User: Brahma Vamsi. AI assistant: Vexa."


def get_all_tags() -> List[str]:
    """Return all known tags — useful for debugging."""
    return sorted(_tag_index.keys())


def get_stats() -> dict:
    """Return knowledge base statistics."""
    return {
        "total_nodes": len(_node_cache),
        "total_tags": len(_tag_index),
        "domains": list(set(p.split("/")[0] for p in _node_cache.keys())),
        "total_content_chars": sum(len(n["content"]) for n in _node_cache.values())
    }
