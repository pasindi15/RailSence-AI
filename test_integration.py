import asyncio
import importlib.util
import os
import sys
from pathlib import Path
import httpx

ROOT_DIR = Path(__file__).resolve().parent

def load_app(module_name: str, file_path: Path):
    app_dir = file_path.parent
    old_cwd = os.getcwd()
    for mod_name in ["hub_client", "rag", "nlp", "ml", "main"]:
        sys.modules.pop(mod_name, None)
    try:
        os.chdir(app_dir)
        sys.path.insert(0, str(app_dir))
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod.app
    finally:
        os.chdir(old_cwd)

m2_app = load_app("m2_main", ROOT_DIR / "M2-operations-agent" / "main.py")
m1_app = load_app("m1_main", ROOT_DIR / "M1-passenger_assistant" / "backend" / "main.py")


async def test_m2_standalone():
    print("=== Testing M2 Operations Agent Standalone ===")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=m2_app), base_url="http://testserver") as m2_client:
        # 1. Health check
        res = await m2_client.get("/health")
        assert res.status_code == 200
        print("M2 /health:", res.json())

        # 2. Direct prediction
        pred_res = await m2_client.post("/predict-delay", json={
            "route": "Colombo Fort - Kandy",
            "train_id": "PM-4082",
            "scheduled_time": "2026-09-12T14:35:00Z"
        })
        assert pred_res.status_code == 200
        pdata = pred_res.json()
        assert "predicted_delay_minutes" in pdata
        assert "explanation" in pdata
        assert "similar_past_incidents" in pdata
        print("M2 Direct Prediction Success! Predicted delay:", pdata["predicted_delay_minutes"])
        print("Explanation:", pdata["explanation"])

        # 3. Internal Hub message handling
        msg_res = await m2_client.post("/internal/messages", json={
            "message_id": "MSG-9999",
            "sender_agent": "passenger-agent",
            "receiver_agent": "operations-agent",
            "intent": "delay_check",
            "payload": {
                "stations": ["Colombo Fort", "Kandy"],
                "raw_text": "Is train PM-4082 delayed?",
                "time": "14:35"
            },
            "auth_token": "dummy-token",
            "timestamp": "2026-09-12T14:35:00Z"
        })
        assert msg_res.status_code == 200
        hub_payload = msg_res.json()
        assert hub_payload["intent"] == "delay_check_response"
        assert "reason" in hub_payload["payload"]
        assert "similar_incident" in hub_payload["payload"]
        print("M2 Internal Hub Message Success! Response:", hub_payload["payload"]["reason"])


async def test_m1_m3_m2_end_to_end():
    print("\n=== Testing M1 -> M3 -> M2 End-to-End Flow ===")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=m1_app), base_url="http://testserver") as m1_client:
        chat_res = await m1_client.post("/chat", json={
            "session_id": "session-test-100",
            "message": "Is the 14:35 train PM-4082 from Colombo Fort to Kandy delayed?"
        })
        assert chat_res.status_code == 200
        data = chat_res.json()
        print("M1 Chat Response:")
        print("  Intent:", data["intent"])
        print("  Language:", data["language"])
        print("  Reply:", data["reply"])
        print("  Source:", data["source"])
        assert data["intent"] == "delay_check"
        assert "Expected delay:" in data["reply"]
        print("\nALL INTEGRATION TESTS PASSED 100% SUCCESS!")


async def main():
    await test_m2_standalone()
    await test_m1_m3_m2_end_to_end()


if __name__ == "__main__":
    asyncio.run(main())
