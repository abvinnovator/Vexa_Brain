# Vexa Brain — Architecture & Capabilities

> **Version**: 2.0.0 | **Architecture**: OKF (Open Knowledge Format)
> **Engine**: FastAPI + Groq LLM + MongoDB + Self-Learning Knowledge Base

---

## What is Vexa Brain?

Vexa Brain is the **AI thinking engine** behind the Vexa personal assistant. It powers:

1. **Phone Automation** — Generates step-by-step action plans for Android phone control
2. **Self-Learning Memory** — Grows smarter with every conversation using OKF knowledge base
3. **Personalized Responses** — Matches the user's communication style and personality
4. **Behavioral Intelligence** — Learns from phone usage patterns via MongoDB observation data

The Android app sends user requests to Vexa Brain's API. The Brain thinks, plans, and returns structured instructions the app can execute.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        VEXA BRAIN (FastAPI)                     │
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐         │
│  │ /api/chat │───▶│ Memory Agent │───▶│ Planner Agent │──┐      │
│  └──────────┘    └──────┬───────┘    └───────────────┘  │      │
│                         │                                │      │
│              ┌──────────┼──────────┐                     │      │
│              ▼          ▼          ▼                     ▼      │
│        ┌──────────┐ ┌────────┐ ┌────────────┐   ┌──────────┐  │
│        │ MongoDB  │ │  OKF   │ │Personality │   │  Groq    │  │
│        │Behavioral│ │Knowledge│ │  Service   │   │  LLM     │  │
│        │ Context  │ │ Service │ │            │   │(llama3)  │  │
│        └──────────┘ └────────┘ └────────────┘   └──────────┘  │
│                         │                                │      │
│                         ▼                                │      │
│                  ┌──────────────┐                        │      │
│                  │   Learning   │◀───────────────────────┘      │
│                  │   Service    │  (async, post-response)       │
│                  └──────┬───────┘                               │
│                         │                                       │
│                         ▼                                       │
│                  ┌──────────────┐                               │
│                  │  OKF Files   │                               │
│                  │ (knowledge/) │                               │
│                  └──────────────┘                               │
│                                                                 │
│  ┌─────────────────┐  ┌──────────────────┐                     │
│  │/api/action/next │  │/api/action/recover│  (UNCHANGED)        │
│  │Interactive Agent │  │ Recovery Agent    │                     │
│  └─────────────────┘  └──────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent Pipeline

### Request Flow: User → Response

```
1. User sends message via Android app
   ↓
2. POST /api/chat { userId, prompt, conversationHistory }
   ↓
3. MemoryAgent.enrich()
   ├── Query MongoDB for behavioral context (app usage, searches, sessions)
   ├── Query OKF knowledge base for relevant facts (tag matching)
   └── Build personality prompt (time-of-day, intent-based tone)
   ↓
4. PlannerAgent.plan()
   ├── Inject: behavioral context + OKF knowledge + personality
   ├── LLM generates: intent, confidence, reply, action steps
   └── Returns structured JSON with ActionPlan
   ↓
5. Return ChatResponse to Android app
   ↓
6. LearningService.process_conversation() [async, non-blocking]
   ├── Extract facts from user message using LLM
   ├── Classify facts into domains (personal, career, preference, etc.)
   └── Merge into OKF knowledge files (with deduplication)
```

### Agents

| Agent | File | Purpose | Modified? |
|-------|------|---------|-----------|
| **MemoryAgent** | `agents/memory_agent.py` | Builds context from MongoDB + OKF + personality | ✅ Updated |
| **PlannerAgent** | `agents/planner_agent.py` | Generates intent + action plan via LLM | ✅ Updated |
| **InteractiveAgent** | `agents/interactive_agent.py` | Step-by-step phone control from screen snapshots | ❌ Unchanged |
| **RecoveryAgent** | `agents/recovery_agent.py` | Handles failed action step recovery | ❌ Unchanged |

---

## OKF Knowledge Base

### What is OKF?

OKF (Open Knowledge Format) is a structured way to organize AI agent knowledge using Markdown files with YAML frontmatter. Instead of dumping everything into one flat file and sending ALL of it to the LLM, OKF:

- **Structures** knowledge into categorized nodes
- **Tags** each node for efficient retrieval
- **Retrieves** only relevant nodes per query
- **Grows** automatically from conversations

### Directory Structure

```
knowledge/
├── index.md                       # Master catalog
├── identity/
│   ├── personal.md                # Name, education, location
│   └── professional.md            # Skills, career, projects
├── preferences/
│   ├── communication.md           # Response style preferences
│   └── apps_and_tools.md          # App & workflow preferences
├── memory/
│   ├── career_events.md           # Job milestones, interviews
│   ├── conversations.md           # Important conversation insights
│   └── temporal.md                # Time-sensitive facts
├── speech/
│   └── profile.md                 # Speaking style, Telugu phrases
└── relationships/
    └── contacts.md                # Known people & context
```

### OKF File Format

Each file has YAML frontmatter that the knowledge service uses for indexing:

```yaml
---
type: knowledge
title: "Vamsi's Professional Profile"
description: "Skills, work history, current role"
tags: [career, skills, cognizant, projects]
last_updated: "2026-07-02"
confidence: 0.95
source: conversation
---

# Professional Profile
(Markdown content here)
```

### How Retrieval Works

1. User says: "What's my interview status?"
2. Knowledge service extracts keywords: `["interview", "status"]`
3. Tags matched: `interview` → `memory/career_events.md`, `identity/professional.md`
4. Returns ONLY those nodes (~200 tokens) instead of everything (~2000+ tokens)

### Token Savings

| Metric | Before (v1) | After (v2) |
|--------|------------|------------|
| Memory context per request | ~800 tokens (ALL of memory.txt) | ~200 tokens (relevant nodes only) |
| Speech profile per request | ~400 tokens (ALL) | ~100 tokens (compact) |
| Total per request | ~3200 tokens | ~1100-1500 tokens |
| **Savings** | — | **~55-65% fewer tokens** |

---

## Self-Learning System

### How Vexa Learns

After every conversation, the learning service runs asynchronously:

1. **Extract**: LLM analyzes the user message for new facts
2. **Classify**: Each fact is routed to the correct OKF domain
3. **Merge**: Facts are written to the appropriate knowledge file with deduplication
4. **Profile**: Communication patterns are tracked and updated

### Fact Types

| Type | Example | OKF Target |
|------|---------|------------|
| `FACT_PERSONAL` | "I moved to Hyderabad" | `identity/personal.md` |
| `FACT_CAREER` | "I got promoted to SSE" | `memory/career_events.md` |
| `FACT_PREFERENCE` | "Always use dark mode" | `preferences/communication.md` |
| `FACT_TEMPORAL` | "Interview results next week" | `memory/temporal.md` |
| `SPEECH_PATTERN` | "Uses 'aina kooda' for emphasis" | `speech/profile.md` |
| `RELATIONSHIP` | "Ravi is my team lead" | `relationships/contacts.md` |

### Deduplication

The system checks if a fact already exists before adding it. If a new fact contradicts an existing one (e.g., old job vs new job), the newer fact takes precedence.

---

## Personalization Engine

### How Responses are Personalized

The personality service builds a dynamic instruction block for the LLM based on:

1. **Speech Profile** — Learned patterns, slang, language mixing
2. **Communication Preferences** — Brevity vs detail, formatting style
3. **Time of Day** — Morning (energetic) vs late night (calm)
4. **Intent Type** — Action requests (efficient) vs conversation (warm)

This is injected into the planner's system prompt, so the `reply` field in the response sounds natural and personal.

> **Note**: Only the conversational `reply` field is affected. The action step format (`OPEN_APP`, `TAP_ELEMENT`, etc.) is completely unchanged.

---

## API Reference

### Core Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Main brain endpoint — takes prompt, returns reply + action plan |
| `POST` | `/api/action/recover` | Recovery endpoint for failed action steps |
| `GET` | `/api/health` | Health check |
| `GET` | `/` | Server info |

### Knowledge Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/knowledge/stats` | Knowledge base statistics |
| `GET` | `/api/knowledge/tags` | All indexed tags |
| `GET` | `/api/knowledge/query?q=...` | Test knowledge retrieval |

### Chat Request/Response

**Request:**
```json
{
  "userId": "vamsi_001",
  "prompt": "Book me an Uber to office",
  "conversationHistory": [
    {"role": "user", "content": "previous message"},
    {"role": "assistant", "content": "previous reply"}
  ]
}
```

**Response:**
```json
{
  "reply": "On it, opening Uber now.",
  "isAction": true,
  "actionPlan": {
    "planId": "uuid",
    "userPrompt": "Book me an Uber to office",
    "intent": "BOOK_RIDE",
    "confidence": 0.95,
    "actions": [
      {
        "step": 1,
        "type": "OPEN_APP",
        "params": {"packageName": "com.ubercab"},
        "description": "Open Uber app",
        "requiresConfirmation": false
      }
    ],
    "requiresUserConfirmation": false
  }
}
```

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Framework | FastAPI | Async REST API server |
| LLM Provider | Groq (llama-3.3-70b) | Fast inference for planning & learning |
| Database | MongoDB (Motor async) | Phone behavioral data storage |
| Knowledge Base | OKF (Markdown + YAML) | Structured personal knowledge |
| Deployment | Docker / Render | Container-based deployment |

---

## Future Roadmap

- [ ] **Google Drive Integration** — Search and retrieve files from Drive (requires OAuth2 flow)
- [ ] **RAG Layer** — Add Pinecone/ChromaDB for large-corpus search when knowledge grows beyond OKF
- [ ] **Voice Assistant Integration** — Connect to Vexa voice assistant (root project)
- [ ] **Multi-user Support** — Per-user knowledge directories
- [ ] **Knowledge Decay** — Auto-archive facts not referenced in 90+ days
- [ ] **Conversation Summarization** — Periodic conversation summaries stored as knowledge nodes
