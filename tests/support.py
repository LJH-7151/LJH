"""Shared HTTP fixture; every test uses isolated, fictional workspace data."""

import base64
import http.client
import json
import shutil
import threading
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlencode

from evidence_app.server import LocalServer
from evidence_app.service import Workspace


class HTTPFixture(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(__file__).resolve().parents[1] / "output" / "tests"
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.data_path = self.test_root / ("test-" + uuid.uuid4().hex)
        self.data_path.mkdir()
        self.addCleanup(self.remove_storage)
        self.addCleanup(self.stop_server)
        self.start_server()

    def remove_storage(self):
        self.assertFalse(self.data_path.is_symlink(), "Refusing to clean a symlink")
        self.assertEqual(self.data_path.resolve().parent, self.test_root.resolve())
        shutil.rmtree(self.data_path)

    def start_server(self):
        self.server = LocalServer(("127.0.0.1", 0), Workspace(self.data_path))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        server = getattr(self, "server", None)
        if server is not None:
            server.shutdown()
            server.server_close()
            self.thread.join(timeout=5)
            self.server = None
            self.assertFalse(self.thread.is_alive(), "HTTP server did not stop")

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def json_request(self, method, path, payload=None, headers=None):
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        status, response_headers, raw = self.request(method, path, body, request_headers)
        self.assertIn("application/json", response_headers.get("Content-Type", ""))
        return status, json.loads(raw.decode("utf-8"))

    def upload(self, raw, name="fictional-company.md", headers=None):
        upload_headers = {"X-Local-Token": self.server.token}
        upload_headers.update(headers or {})
        return self.json_request(
            "POST",
            "/api/upload",
            {"name": name, "content": base64.b64encode(raw).decode("ascii")},
            upload_headers,
        )

    def documents(self):
        status, payload = self.json_request("GET", "/api/documents")
        self.assertEqual(status, 200)
        return payload["documents"]

    def document_path(self, endpoint, document):
        return endpoint + "?" + urlencode({"id": document["id"]})
