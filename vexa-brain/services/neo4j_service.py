"""
Neo4j Graph Database Service — OKF v0.2 Graph Persistence Layer.

Stores OKF knowledge nodes in Neo4j graph database so that learned knowledge
persists across server restarts and deployments (e.g. Render ephemeral storage).

Graph Schema:
  (:Domain {name}) -[:BELONGS_TO]<- (:OKFNode {path, domain, filename, title, type, confidence, last_updated, status, content}) -[:HAS_TAG]-> (:Tag {name})
"""

import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import yaml
from datetime import datetime

try:
    from neo4j import AsyncGraphDatabase, AsyncDriver
except ImportError:
    AsyncGraphDatabase = None
    AsyncDriver = None

from config import settings

logger = logging.getLogger(__name__)

_driver: Optional[AsyncDriver] = None


async def connect():
    """Connect to Neo4j database."""
    global _driver
    if not settings.neo4j_uri or not settings.neo4j_username or not settings.neo4j_password:
        logger.warning("Neo4j configuration incomplete. Graph DB will be disabled.")
        return

    if AsyncGraphDatabase is None:
        logger.warning("neo4j package not installed. Graph DB disabled.")
        return

    try:
        auth = (settings.neo4j_username, settings.neo4j_password)
        _driver = AsyncGraphDatabase.driver(settings.neo4j_uri, auth=auth)
        # Verify connection
        async with _driver.session(database=settings.neo4j_database or None) as session:
            result = await session.run("RETURN 1 as ok")
            record = await result.single()
            if record and record["ok"] == 1:
                logger.info("Connected successfully to Neo4j Graph DB!")
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        _driver = None


async def disconnect():
    """Close Neo4j driver connection."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


def is_connected() -> bool:
    return _driver is not None


async def fetch_all_nodes() -> List[Dict]:
    """Fetch all OKF nodes from Neo4j."""
    if not _driver:
        return []

    query = """
    MATCH (n:OKFNode)
    OPTIONAL MATCH (n)-[:HAS_TAG]->(t:Tag)
    RETURN n.path as path,
           n.domain as domain,
           n.filename as filename,
           n.title as title,
           n.type as type,
           n.confidence as confidence,
           n.last_updated as last_updated,
           n.status as status,
           n.content as content,
           collect(t.name) as tags
    """
    try:
        async with _driver.session(database=settings.neo4j_database or None) as session:
            result = await session.run(query)
            records = await result.data()
            return records
    except Exception as e:
        logger.error(f"Failed to fetch nodes from Neo4j: {e}")
        return []


async def upsert_node(
    domain: str,
    filename: str,
    title: str,
    node_type: str,
    tags: List[str],
    confidence: float,
    last_updated: str,
    status: str,
    content: str
):
    """Create or update an OKF node in Neo4j with its tags and domain relationship."""
    if not _driver:
        return

    path = f"{domain}/{filename}.md"

    query = """
    MERGE (d:Domain {name: $domain})
    MERGE (n:OKFNode {path: $path})
    SET n.domain = $domain,
        n.filename = $filename,
        n.title = $title,
        n.type = $type,
        n.confidence = $confidence,
        n.last_updated = $last_updated,
        n.status = $status,
        n.content = $content
    MERGE (n)-[:BELONGS_TO]->(d)
    WITH n
    UNWIND $tags as tagName
    MERGE (t:Tag {name: toLower(tagName)})
    MERGE (n)-[:HAS_TAG]->(t)
    """

    try:
        async with _driver.session(database=settings.neo4j_database or None) as session:
            await session.run(
                query,
                domain=domain,
                path=path,
                filename=filename,
                title=title,
                type=node_type,
                confidence=confidence,
                last_updated=last_updated,
                status=status,
                content=content,
                tags=tags or [domain, filename]
            )
            logger.info(f"Neo4j: Upserted node {path}")
    except Exception as e:
        logger.error(f"Failed to upsert node {path} in Neo4j: {e}")


async def search_content(keywords: List[str], max_results: int = 5) -> List[Dict]:
    """
    Full-text search across all OKF node content in Neo4j.
    Used as a fallback when tag/heading matching returns weak results.

    Returns list of dicts with: path, title, snippet (matching content excerpt).
    """
    if not _driver or not keywords:
        return []

    # Build a WHERE clause that matches any keyword in content (case-insensitive)
    conditions = " OR ".join([f"toLower(n.content) CONTAINS toLower($kw{i})" for i in range(len(keywords))])
    query = f"""
    MATCH (n:OKFNode)
    WHERE {conditions}
    RETURN n.path as path,
           n.title as title,
           n.content as content
    LIMIT $max_results
    """

    params = {f"kw{i}": kw for i, kw in enumerate(keywords)}
    params["max_results"] = max_results

    try:
        async with _driver.session(database=settings.neo4j_database or None) as session:
            result = await session.run(query, **params)
            records = await result.data()

            # Extract relevant snippets from matched content
            results = []
            for record in records:
                content = record.get("content", "")
                snippet = _extract_snippet(content, keywords)
                results.append({
                    "path": record.get("path", ""),
                    "title": record.get("title", ""),
                    "snippet": snippet
                })

            logger.info(f"Neo4j content search: {len(results)} results for keywords {keywords}")
            return results
    except Exception as e:
        logger.error(f"Neo4j content search failed: {e}")
        return []


def _extract_snippet(content: str, keywords: List[str], context_chars: int = 300) -> str:
    """Extract a relevant snippet from content around the first matching keyword."""
    content_lower = content.lower()

    for kw in keywords:
        idx = content_lower.find(kw.lower())
        if idx >= 0:
            # Find the line containing the match and surrounding lines
            start = max(0, content.rfind("\n", 0, idx))
            end = content.find("\n", idx + len(kw))
            if end == -1:
                end = len(content)

            # Expand to include surrounding context
            line_start = max(0, content.rfind("\n", 0, start))
            line_end = content.find("\n", end + 1)
            if line_end == -1:
                line_end = len(content)

            snippet = content[line_start:min(line_end, line_start + context_chars)].strip()
            return snippet

    # No match found — return first N chars
    return content[:context_chars].strip() if content else ""


async def seed_from_markdown_if_empty(knowledge_dir: Path):
    """Seed Neo4j database from local Markdown files on initial setup if Neo4j is empty."""
    if not _driver:
        return

    existing = await fetch_all_nodes()
    if existing:
        logger.info(f"Neo4j already contains {len(existing)} OKF nodes. Skipping initial seed.")
        return

    logger.info("Neo4j database is empty. Seeding initial OKF nodes from Markdown directory...")
    md_files = list(knowledge_dir.rglob("*.md"))

    for filepath in md_files:
        if filepath.name == "index.md":
            continue

        try:
            rel_path = str(filepath.relative_to(knowledge_dir)).replace("\\", "/")
            parts = rel_path.split("/")
            domain = parts[0] if len(parts) > 1 else "general"
            filename = filepath.stem

            text = filepath.read_text(encoding="utf-8")
            frontmatter = {}
            content = text

            if text.startswith("---"):
                parts_text = text.split("---", 2)
                if len(parts_text) >= 3:
                    frontmatter = yaml.safe_load(parts_text[1]) or {}
                    content = parts_text[2].strip()

            await upsert_node(
                domain=domain,
                filename=filename,
                title=frontmatter.get("title", f"{domain}/{filename}"),
                node_type=frontmatter.get("type", "knowledge"),
                tags=frontmatter.get("tags", [domain, filename]),
                confidence=float(frontmatter.get("confidence", 0.9)),
                last_updated=str(frontmatter.get("last_updated", datetime.now().strftime("%Y-%m-%d"))),
                status=str(frontmatter.get("status", "stable")),
                content=content
            )
        except Exception as e:
            logger.error(f"Failed to seed file {filepath} to Neo4j: {e}")

    logger.info("Neo4j seeding complete.")
