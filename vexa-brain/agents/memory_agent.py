from services import mongodb_service, knowledge_service, personality_service
from models.request_models import VexaMemory
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Known package → app category mapping
APP_CATEGORIES = {
    "com.ubercab": "Ride",
    "com.olacabs.customer": "Ride",
    "com.rapido.passenger": "Ride",
    "com.grofers.customerapp": "Grocery",
    "com.zomato.android": "Food",
    "app.swiggy.android": "Food",
    "in.redbus.android": "Travel",
    "com.makemytrip": "Travel",
    "com.reddit.frontpage": "Social",
    "com.instagram.android": "Social",
    "com.whatsapp": "Messaging",
    "com.google.android.youtube": "Entertainment",
    "com.spotify.music": "Entertainment",
    "com.phonepe.app": "Payments",
    "com.google.android.apps.nbu.paisa.user": "Payments",
}


async def enrich(memory: VexaMemory) -> VexaMemory:
    """
    MemoryAgent: Builds context from multiple sources.

    1. MongoDB behavioral data (phone observation — UNCHANGED)
    2. OKF knowledge retrieval (NEW — smart, relevant-only)
    3. Personality prompt (NEW — dynamic style matching)
    """
    uid = memory.user_id

    # ── 1. Behavioral context from MongoDB (UNCHANGED) ──
    try:
        # Top apps by usage
        app_usage = await mongodb_service.get_app_usage_frequency(uid, days=7)
        top_apps = [
            f"{a['appName']} ({a['count']} events)"
            for a in app_usage[:5]
        ]

        # Uber destinations
        uber_destinations = await mongodb_service.get_uber_destinations(uid)

        # Recent sessions summary
        sessions = await mongodb_service.get_recent_sessions(uid, limit=3)
        session_summaries = []
        for s in sessions:
            apps = ", ".join(s.get("apps", []))
            count = s.get("eventCount", 0)
            session_summaries.append(f"Session with {apps} ({count} events)")

        # Food/grocery searches
        blinkit_searches = await mongodb_service.get_typed_searches(uid, "com.grofers.customerapp")
        zomato_searches  = await mongodb_service.get_typed_searches(uid, "com.zomato.android")

        # Recent raw events (for deep context)
        recent = await mongodb_service.get_recent_events(uid, hours=24)
        recent_summary = _summarize_recent_events(recent)

        memory.behavioral_context = f"""USER BEHAVIORAL PROFILE (from phone observation data):

Top apps used this week:
{chr(10).join(f'  - {a}' for a in top_apps) or '  - No data yet'}

Recent Uber/ride destinations typed:
{chr(10).join(f'  - {d}' for d in uber_destinations[:5]) or '  - No ride history'}

Recent food/grocery searches:
  Blinkit: {', '.join(blinkit_searches[:5]) or 'none'}
  Zomato: {', '.join(zomato_searches[:5]) or 'none'}

Recent activity summary (last 24h):
{recent_summary}

Recent sessions:
{chr(10).join(f'  - {s}' for s in session_summaries) or '  - No recent sessions'}

Current time: {datetime.now().strftime('%A %I:%M %p')}""".strip()

        logger.info(f"MemoryAgent: behavioral context built for user {uid}")

    except Exception as e:
        logger.error(f"MemoryAgent behavioral context error: {e}")
        memory.behavioral_context = "No behavioral context available."

    # ── 2. OKF Knowledge Retrieval (NEW) ──
    try:
        memory.knowledge_context = await knowledge_service.query_relevant(
            memory.raw_prompt, uid
        )
        memory.communication_profile = await knowledge_service.get_communication_profile()
        logger.info(f"MemoryAgent: OKF knowledge retrieved ({len(memory.knowledge_context)} chars)")
    except Exception as e:
        logger.error(f"MemoryAgent OKF error: {e}")
        memory.knowledge_context = ""
        memory.communication_profile = ""

    # ── 3. Personality Prompt (NEW) ──
    try:
        memory.personality_prompt = await personality_service.build_personality_prompt()
    except Exception as e:
        logger.error(f"MemoryAgent personality error: {e}")
        memory.personality_prompt = ""

    return memory


def _summarize_recent_events(events: list) -> str:
    """Collapse raw events into a readable summary."""
    if not events:
        return "  No recent activity"

    app_switches = []
    typed_inputs = []
    button_taps = []

    for e in events[:50]:
        pkg = e.get("appName") or e.get("packageName", "")
        etype = e.get("eventType", "")
        if etype == "WINDOW_STATE_CHANGED" and e.get("screenTitle"):
            app_switches.append(f"{pkg} → {e['screenTitle']}")
        elif etype == "VIEW_TEXT_CHANGED" and e.get("typedText"):
            hint = e.get("fieldHint", "field")
            app_switches.append(f"Typed '{e['typedText']}' in [{hint}] in {pkg}")
        elif etype == "VIEW_CLICKED" and e.get("buttonLabel"):
            button_taps.append(f"Tapped '{e['buttonLabel']}' in {pkg}")

    lines = []
    if app_switches:
        lines.append("  Screens visited: " + "; ".join(app_switches[:5]))
    if button_taps:
        lines.append("  Buttons tapped: " + "; ".join(button_taps[:5]))

    return "\n".join(lines) if lines else "  Light activity"
