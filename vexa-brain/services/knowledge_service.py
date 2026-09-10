"""
Knowledge Service — OKF-based smart retrieval engine with Neo4j Graph DB backend.

v3.0: Enhanced retrieval with LLM semantic query expansion, micro-section
indexing for bullet-point facts, improved scoring, and Neo4j full-text fallback.

Reads structured Markdown files with YAML frontmatter on initial boot,
persists all learned knowledge into Neo4j Graph Database, and returns
ONLY the knowledge nodes relevant to the current user query.

Token budget: ~300-600 tokens per request (vs ~2000+ before).
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

# Maximum context character budget for retrieved sections (increased from 1800)
MAX_CONTEXT_CHARS = 3000

# Tag-to-file mapping — built on startup from frontmatter
_tag_index: Dict[str, List[str]] = {}
_node_cache: Dict[str, dict] = {}       # rel_path -> {frontmatter, content, path}
_section_cache: List[dict] = []         # [{file_rel_path, file_title, heading, content, tags, keywords}]


def init():
    """Synchronous init fallback for local file loading."""
    _load_from_files()


def _parse_sections(rel_path: str, title: str, tags: List[str], content: str) -> List[dict]:
    """Split markdown content into heading sections AND individual bullet-point facts."""
    sections = []
    lines = content.splitlines()

    current_heading = "Overview"
    current_lines = []

    for line in lines:
        match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
        if match:
            # Save previous section if non-empty
            section_text = "\n".join(current_lines).strip()
            if section_text:
                sections.append({
                    "file_rel_path": rel_path,
                    "file_title": title,
                    "heading": current_heading,
                    "content": section_text,
                    "tags": tags,
                    "heading_keywords": set(re.findall(r'[a-z0-9]+', current_heading.lower()))
                })
            current_heading = match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Add final section
    section_text = "\n".join(current_lines).strip()
    if section_text:
        sections.append({
            "file_rel_path": rel_path,
            "file_title": title,
            "heading": current_heading,
            "content": section_text,
            "tags": tags,
            "heading_keywords": set(re.findall(r'[a-z0-9]+', current_heading.lower()))
        })

    # ── Micro-section indexing: index individual bullet-point facts ──
    # This makes appended facts from the learning service individually searchable
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") and len(stripped) > 15:
            fact_text = stripped[2:].strip()
            # Extract keywords from the fact itself for better matching
            fact_keywords = set(re.findall(r'[a-z0-9]+', fact_text.lower()))
            # Remove very common words to keep keywords meaningful
            fact_keywords -= {"the", "a", "an", "is", "are", "was", "were", "has", "have",
                            "and", "or", "but", "for", "with", "from", "that", "this",
                            "user", "users", "not", "also", "their", "them", "they",
                            "mentioned", "context", "explicitly", "bot", "reply"}

            if len(fact_keywords) >= 2:  # Only index facts with meaningful keywords
                sections.append({
                    "file_rel_path": rel_path,
                    "file_title": title,
                    "heading": f"Fact: {fact_text[:60]}",
                    "content": fact_text,
                    "tags": tags,
                    "heading_keywords": fact_keywords,
                    "is_micro_fact": True
                })

    return sections


def _rebuild_section_cache():
    """Build section-level chunk cache from all node cache items."""
    global _section_cache
    _section_cache = []
    for rel_path, node in _node_cache.items():
        fm = node.get("frontmatter", {})
        title = fm.get("title", rel_path)
        tags = fm.get("tags", [])
        content = node.get("content", "")
        sec_list = _parse_sections(rel_path, title, tags, content)
        _section_cache.extend(sec_list)


async def init_async():
    """Initialize knowledge service with Neo4j Graph Database support."""
    global _tag_index, _node_cache
    _tag_index = {}
    _node_cache = {}

    await neo4j_service.connect()

    if neo4j_service.is_connected():
        if KNOWLEDGE_BASE_DIR.exists():
            await neo4j_service.seed_from_markdown_if_empty(KNOWLEDGE_BASE_DIR)

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

            for tag in tags:
                if tag:
                    tag_lower = tag.lower()
                    if tag_lower not in _tag_index:
                        _tag_index[tag_lower] = []
                    if rel_path not in _tag_index[tag_lower]:
                        _tag_index[tag_lower].append(rel_path)

            title = frontmatter.get("title", "")
            for word in title.lower().split():
                word = re.sub(r'[^a-z0-9]', '', word)
                if len(word) > 2:
                    if word not in _tag_index:
                        _tag_index[word] = []
                    if rel_path not in _tag_index[word]:
                        _tag_index[word].append(rel_path)

        _rebuild_section_cache()
        logger.info(f"Knowledge service (Neo4j): indexed {len(_node_cache)} nodes, {len(_section_cache)} sections, {len(_tag_index)} tags")
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

            tags = frontmatter.get("tags", [])
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in _tag_index:
                    _tag_index[tag_lower] = []
                _tag_index[tag_lower].append(rel_path)

            title = frontmatter.get("title", "")
            for word in title.lower().split():
                word = re.sub(r'[^a-z0-9]', '', word)
                if len(word) > 2:
                    if word not in _tag_index:
                        _tag_index[word] = []
                    _tag_index[word].append(rel_path)

        except Exception as e:
            logger.warning(f"Failed to parse OKF node {md_file}: {e}")

    _rebuild_section_cache()
    logger.info(f"Knowledge service (Filesystem): indexed {len(_node_cache)} nodes, {len(_section_cache)} sections, {len(_tag_index)} tags")


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


async def _semantic_expand_query(user_prompt: str) -> List[str]:
    """
    Use a fast LLM call to expand the user's query into semantically related search terms.
    This bridges the gap between user language and stored knowledge terms.
    """
    try:
        from services import llm_service

        messages = [
            {"role": "system", "content": "You are a search query expansion engine. Given a user query, output 8-12 related search keywords/terms that would help find relevant personal facts, memories, or knowledge. Include synonyms, related concepts, abbreviations expanded, and alternate phrasings. Output ONLY comma-separated keywords, nothing else."},
            {"role": "user", "content": f"Expand this query into search terms: \"{user_prompt}\""}
        ]

        response = await llm_service.chat(messages, temperature=0.1, max_tokens=100, agent_name="retrieval")
        expanded = response.strip()

        # Parse comma-separated keywords
        expanded_keywords = []
        for term in expanded.split(","):
            term = term.strip().lower()
            words = re.findall(r'[a-z0-9]+', term)
            expanded_keywords.extend(words)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for kw in expanded_keywords:
            if kw not in seen and len(kw) > 1:
                seen.add(kw)
                unique.append(kw)

        logger.info(f"Semantic expansion: '{user_prompt[:50]}' → {unique[:15]}")
        return unique[:15]

    except Exception as e:
        logger.warning(f"Semantic query expansion failed (falling back to keywords): {e}")
        return []


async def query_relevant(user_prompt: str, user_id: str = "") -> str:
    """
    Enhanced Section-level OKF Retrieval Engine v3.0:
    1. Extract keywords from user prompt
    2. Expand query semantically via LLM
    3. Score sections with improved weights (content > tags > headings)
    4. Fall back to Neo4j full-text search if needed
    5. Always include identity baseline context
    """
    if not _node_cache:
        await init_async()

    if not _section_cache:
        return "No knowledge base available."

    # ── 1. Extract keywords from prompt ──
    base_keywords = set(_extract_keywords(user_prompt))

    # ── 2. Semantic LLM expansion ──
    expanded_keywords = await _semantic_expand_query(user_prompt)
    all_keywords = base_keywords | set(expanded_keywords)

    logger.info(f"Retrieval keywords: base={base_keywords}, expanded={set(expanded_keywords) - base_keywords}")

    # ── 3. Score sections with improved weights ──
    section_scores: List[Tuple[dict, float]] = []

    for sec in _section_cache:
        score = 0.0
        heading_kw = sec["heading_keywords"]
        content_lower = sec["content"].lower()
        is_micro = sec.get("is_micro_fact", False)

        # (a) Heading keyword match — strong signal
        heading_matches = all_keywords.intersection(heading_kw)
        score += len(heading_matches) * 3.0

        # (b) For micro-facts, heading_keywords ARE the content keywords — boost heavily
        if is_micro:
            micro_matches = all_keywords.intersection(heading_kw)
            score += len(micro_matches) * 3.0  # Extra boost for micro-facts

        # (c) Tag match for file
        for tag in sec["tags"]:
            tag_lower = str(tag).lower()
            if tag_lower in all_keywords:
                score += 1.5

        # (d) Content substring match — primary signal for appended facts
        for kw in all_keywords:
            if len(kw) < 2:
                continue
            # Exact word match in content
            if kw in content_lower:
                score += 2.0
            # Substring/partial match (e.g., "dsat" matches "dsats")
            elif any(kw in word or word in kw for word in re.findall(r'[a-z0-9]+', content_lower) if len(word) > 2):
                score += 1.2

        # (e) Frequency boost — if a keyword appears multiple times, it's more relevant
        for kw in base_keywords:  # Only base keywords for frequency (avoid noise from expansion)
            count = content_lower.count(kw)
            if count > 1:
                score += min(count * 0.5, 2.0)  # Cap at 2.0 extra

        if score > 0.0:
            section_scores.append((sec, score))

    # ── 4. Neo4j full-text fallback if scores are weak ──
    top_score = section_scores[0][1] if section_scores else 0.0
    if top_score < 2.0 and neo4j_service.is_connected():
        try:
            search_terms = list(base_keywords)[:5]
            neo4j_results = await neo4j_service.search_content(search_terms)
            if neo4j_results:
                logger.info(f"Neo4j fallback found {len(neo4j_results)} results")
                for result in neo4j_results:
                    # Add Neo4j results as high-priority sections
                    section_scores.append(({
                        "file_rel_path": result.get("path", "neo4j"),
                        "file_title": result.get("title", "Memory"),
                        "heading": "Memory Search Result",
                        "content": result.get("snippet", ""),
                        "tags": [],
                        "heading_keywords": set(),
                    }, 5.0))
        except Exception as e:
            logger.warning(f"Neo4j fallback search failed: {e}")

    if not section_scores:
        return _get_identity_summary()

    # Sort sections by highest score first
    section_scores.sort(key=lambda x: x[1], reverse=True)
    top_score = section_scores[0][1]

    context_parts = []
    total_chars = 0
    seen_section_keys = set()

    # ── Always include identity baseline (compact) ──
    identity_summary = _get_compact_identity()
    if identity_summary:
        context_parts.append(f"[Identity Summary]\n{identity_summary}")
        total_chars += len(context_parts[-1])

    for sec, score in section_scores:
        # Lower threshold: was max(2.0, top_score * 0.4), now max(1.0, top_score * 0.3)
        if score < max(1.0, top_score * 0.3):
            continue

        sec_key = f"{sec['file_rel_path']}#{sec['heading']}"
        if sec_key in seen_section_keys:
            continue
        seen_section_keys.add(sec_key)

        # Skip identity sections since we already included the baseline
        if sec["file_rel_path"] == "identity/personal.md" and sec["heading"] in ("Identity", "Overview"):
            continue

        formatted_chunk = f"[{sec['file_title']} > {sec['heading']}]\n{sec['content']}"

        if total_chars + len(formatted_chunk) > MAX_CONTEXT_CHARS and context_parts:
            break

        context_parts.append(formatted_chunk)
        total_chars += len(formatted_chunk)

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

    # 3. Rebuild section cache so new facts are immediately searchable
    _rebuild_section_cache()

    # 4. Persist to Neo4j Graph DB
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
    """Extract meaningful keywords from user text for tag matching.

    v3.0 improvements:
    - Lowered min length from 3 to 2 (catches "pg", "ai", "kg")
    - Preserves numeric tokens
    - Adds singular/plural variations
    """
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
        "many", "much", "does", "don", "t", "re",
    }

    words = re.findall(r'[a-z0-9]+', text.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 1]

    # Add singular/plural variations
    variations = []
    for kw in keywords:
        if kw.endswith("s") and len(kw) > 3:
            variations.append(kw[:-1])  # "dsats" → "dsat"
        elif not kw.endswith("s"):
            variations.append(kw + "s")  # "dsat" → "dsats"
    keywords.extend(variations)

    # Add bigrams for multi-word concepts
    for i in range(len(words) - 1):
        bigram = f"{words[i]}_{words[i+1]}"
        if words[i] not in stop_words and words[i+1] not in stop_words:
            keywords.append(bigram)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)

    return unique[:20]


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


def _get_compact_identity() -> str:
    """Return a compact identity snapshot that's always included in context."""
    key = "identity/personal.md"
    if key not in _node_cache:
        return ""

    content = _node_cache[key]["content"]
    lines = content.splitlines()

    # Extract the structured identity section (up to Goals) — skip appended bullet facts
    compact_lines = []
    for line in lines:
        stripped = line.strip()
        # Stop at the first appended fact (bullet point outside a heading section)
        if stripped.startswith("- ") and not stripped.startswith("- **"):
            # Check if this looks like an appended learning fact (not a structured field)
            if "user" in stripped.lower() or "name" in stripped.lower() or "vamsi" in stripped.lower():
                continue  # Skip redundant name facts
            # Include non-redundant appended facts
            compact_lines.append(stripped)
        else:
            compact_lines.append(line)

    result = "\n".join(compact_lines).strip()
    if len(result) > 500:
        return result[:500] + "..."
    return result


def get_all_tags() -> List[str]:
    return sorted(_tag_index.keys())


def get_stats() -> dict:
    return {
        "total_nodes": len(_node_cache),
        "total_tags": len(_tag_index),
        "total_sections": len(_section_cache),
        "micro_facts": sum(1 for s in _section_cache if s.get("is_micro_fact")),
        "domains": list(set(p.split("/")[0] for p in _node_cache.keys())),
        "total_content_chars": sum(len(n["content"]) for n in _node_cache.values()),
        "neo4j_connected": neo4j_service.is_connected()
    }
