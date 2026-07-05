"""Quick smoke test — verifies all imports and knowledge base initialization."""
import sys
sys.path.insert(0, ".")

# Test all imports
from services import knowledge_service, learning_service, personality_service
from agents import memory_agent, planner_agent, interactive_agent, recovery_agent
from routers import chat, action, knowledge
from models.request_models import (
    ChatRequest, ChatResponse, ActionPlan, ActionStep,
    VexaMemory, NextActionRequest, NextActionResponse,
    RecoveryRequest, RecoveryResponse, ScreenSnapshot
)
print("All imports: OK")

# Test knowledge service
knowledge_service.init()
stats = knowledge_service.get_stats()
print(f"OKF Nodes: {stats['total_nodes']}")
print(f"OKF Tags: {stats['total_tags']}")
print(f"OKF Domains: {stats['domains']}")
print(f"OKF Content: {stats['total_content_chars']} chars")

# Test retrieval
import asyncio

async def test_retrieval():
    r1 = await knowledge_service.query_relevant("what is my interview status")
    r2 = await knowledge_service.query_relevant("order biryani from zomato")
    r3 = await knowledge_service.query_relevant("tell me about myself")
    print(f"\nRetrieval test:")
    print(f"  'interview status' -> {len(r1)} chars (should be ~1000-1600)")
    print(f"  'order biryani'    -> {len(r2)} chars (should be ~40-200, minimal)")
    print(f"  'about myself'     -> {len(r3)} chars (should be ~300-600)")

    # Test communication profile
    profile = await knowledge_service.get_communication_profile()
    print(f"\nCommunication profile: {len(profile)} chars")

    # Test personality prompt
    personality = await personality_service.build_personality_prompt()
    print(f"Personality prompt: {len(personality)} chars")

asyncio.run(test_retrieval())

print("\n--- ALL TESTS PASSED ---")
