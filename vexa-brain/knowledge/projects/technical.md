---
confidence: 0.9
last_updated: "2026-08-05"
status: stable
tags:
  - projects
  - technical
title: projects/technical
type: knowledge
---

- Vexa Brain's architecture is based on OKF (Open Knowledge Format) and uses FastAPI, Groq LLM, MongoDB, and a Self-Learning Knowledge Base.
- The system has a modular design with agents, including MemoryAgent, PlannerAgent, InteractiveAgent, and RecoveryAgent.
- The OKF knowledge base is structured using Markdown files with YAML frontmatter, allowing for efficient retrieval and growth of knowledge.
- The system uses a token-saving approach, retrieving only relevant nodes (~200 tokens) instead of the entire knowledge base (~2000+ tokens).
- The system's self-learning mechanism extracts facts from user messages, classifies them into domains, and merges them into the OKF knowledge files with deduplication.
- The personalization engine builds a dynamic instruction block for the LLM based on the user's speech profile, learned patterns, and language mix.
- FastAPI server running on Render and using groq llm model.
