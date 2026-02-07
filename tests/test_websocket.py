import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module


class WebSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self._ensure_patch = patch.object(app_module, "ensure_schema", lambda: None)
        self._ensure_patch.start()

        async def fake_process(payload):
            return app_module.ChatResponse(
                session_id=payload.call_uuid,
                call_uuid=payload.call_uuid,
                phone_number=payload.phone_number,
                reply="ok",
                language="en",
                intent="chat",
                used_tool=None,
                tool_data=None,
                flow=None,
            )

        self._process_patch = patch.object(app_module, "_process_chat", new=fake_process)
        self._process_patch.start()

    def tearDown(self) -> None:
        self._process_patch.stop()
        self._ensure_patch.stop()

    def test_ws_chat_success(self):
        with TestClient(app_module.app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({
                    "message": "Hello",
                    "phone_number": "9999999999",
                    "call_uuid": "abc-123",
                })
                data = ws.receive_json()
                self.assertEqual(data["type"], "chat")
                self.assertEqual(data["reply"], "ok")
                self.assertEqual(data["call_uuid"], "abc-123")
                self.assertIn("Chat_ended", data)

    def test_ws_invalid_payload(self):
        with TestClient(app_module.app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({
                    "phone_number": "9999999999",
                    "call_uuid": "abc-123",
                })
                data = ws.receive_json()
                self.assertEqual(data["type"], "error")

    def test_ws_ping(self):
        with TestClient(app_module.app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "ping"})
                data = ws.receive_json()
                self.assertEqual(data, {"type": "pong"})

    def test_ws_non_object_payload(self):
        with TestClient(app_module.app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_text("[]")
                data = ws.receive_json()
                self.assertEqual(data["type"], "error")
                self.assertIn("Invalid payload", data["detail"])


if __name__ == "__main__":
    unittest.main()
