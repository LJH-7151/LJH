"""Exercise the Day 1 HTTP contract with fictional documents and isolated storage."""

import base64
import hashlib
import json
import unittest

from evidence_app.service import Workspace
import support


class FoundationHTTPTests(support.HTTPFixture):
    def test_health_identifies_the_foundation_milestone(self):
        status, payload = self.json_request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["version"], "0.1.1")
        self.assertEqual(payload["milestone"], "day2")
        self.assertEqual(self.documents(), [])

    def test_upload_list_text_and_download_form_a_complete_round_trip(self):
        raw = "示例甲公司\n仅供测试的成立说明。\n\n第二段虚构经营范围。\n".encode("utf-8")
        status, result = self.upload(raw, name="示例甲公司.md")
        self.assertEqual(status, 201)
        self.assertIs(result["duplicate"], False)
        document = result["document"]
        required = {"id", "title", "filename", "sha256", "size", "created_at", "chunk_count"}
        self.assertTrue(required.issubset(document))
        self.assertTrue(document["id"])
        self.assertTrue(document["title"])
        self.assertTrue(document["created_at"])
        self.assertEqual(document["filename"], "示例甲公司.md")
        self.assertEqual(document["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(document["size"], len(raw))
        self.assertEqual(document["chunk_count"], 2)
        self.assertEqual(self.documents(), [document])

        status, text = self.json_request(
            "GET", self.document_path("/api/document-text", document)
        )
        self.assertEqual(status, 200)
        self.assertEqual(text["document"], document)
        self.assertEqual(len(text["chunks"]), 2)
        chunks = text["chunks"]
        self.assertEqual(chunks[0]["content"].splitlines(), ["示例甲公司", "仅供测试的成立说明。"])
        self.assertEqual(chunks[1]["content"].splitlines(), ["第二段虚构经营范围。"])
        self.assertEqual([(c["start_line"], c["end_line"]) for c in chunks], [(1, 2), (4, 4)])
        self.assertEqual(len({c["id"] for c in chunks}), 2)
        for chunk in chunks:
            self.assertIsInstance(chunk["position"], int)
            self.assertTrue(chunk["location"])

        status, _, downloaded = self.request("GET", self.document_path("/api/original", document))
        self.assertEqual(status, 200)
        self.assertEqual(downloaded, raw)

    def test_utf8_bom_and_crlf_preserve_original_source_line_numbers(self):
        raw = b"\xef\xbb\xbf" + "虚构公司\r\n第一项说明\r\n\r\n另一段\r\n".encode("utf-8")
        status, result = self.upload(raw, name="bom-source.txt")
        self.assertEqual(status, 201)
        document = result["document"]
        status, text = self.json_request("GET", self.document_path("/api/document-text", document))
        self.assertEqual(status, 200)
        self.assertEqual([(c["start_line"], c["end_line"]) for c in text["chunks"]], [(1, 2), (4, 4)])
        self.assertEqual(text["chunks"][0]["content"].splitlines(), ["虚构公司", "第一项说明"])
        self.assertNotIn("\ufeff", "".join(c["content"] for c in text["chunks"]))
        self.assertEqual(document["sha256"], hashlib.sha256(raw).hexdigest())
        status, _, downloaded = self.request("GET", self.document_path("/api/original", document))
        self.assertEqual(status, 200)
        self.assertEqual(downloaded, raw)

    def test_reupload_is_idempotent_and_keeps_the_same_document(self):
        raw = b"Fictional company\n\nFictional evidence.\n"
        status, first = self.upload(raw)
        self.assertEqual(status, 201)
        status, repeated = self.upload(raw)
        self.assertEqual(status, 200)
        self.assertIs(repeated["duplicate"], True)
        self.assertEqual(repeated["document"], first["document"])
        self.assertEqual(self.documents(), [first["document"]])

    def test_storage_can_be_reopened_and_served_after_restart(self):
        raw = b"Persistent fictional record.\n"
        status, result = self.upload(raw, name="restart.txt")
        self.assertEqual(status, 201)
        document = result["document"]
        self.stop_server()
        restored = Workspace(self.data_path)
        self.assertEqual(restored.documents(), [document])
        self.start_server()
        self.assertEqual(self.documents(), [document])
        status, text = self.json_request("GET", self.document_path("/api/document-text", document))
        self.assertEqual(status, 200)
        self.assertEqual(text["chunks"][0]["content"], "Persistent fictional record.")
        status, _, downloaded = self.request("GET", self.document_path("/api/original", document))
        self.assertEqual(status, 200)
        self.assertEqual(downloaded, raw)

    def test_invalid_uploads_do_not_create_documents(self):
        encoded = base64.b64encode(b"Fictional evidence.").decode("ascii")
        invalid = [
            {"name": "empty.txt", "content": ""},
            {"name": "nul.txt", "content": base64.b64encode(b"text\x00text").decode("ascii")},
            {"name": "invalid-utf8.txt", "content": base64.b64encode(b"\xff\xfe").decode("ascii")},
            {"name": "bad-base64.txt", "content": "%%%not-base64%%%"},
            {"name": "../outside.txt", "content": encoded},
            {"name": "nested\\outside.txt", "content": encoded},
            {"name": "unsupported.pdf", "content": encoded},
            {"name": "wrong-content-type.txt", "content": 42},
            {"name": 42, "content": encoded},
            {"content": encoded},
        ]
        for payload in invalid:
            with self.subTest(name=payload.get("name")):
                status, error = self.json_request(
                    "POST", "/api/upload", payload, {"X-Local-Token": self.server.token}
                )
                self.assertEqual(status, 400)
                self.assertIn("error", error)
                self.assertEqual(self.documents(), [])

    def test_document_size_limit_rejects_excess_without_persisting_it(self):
        status, error = self.upload(b"x" * (2 * 1024 * 1024 + 1), name="oversize.txt")
        self.assertIn(status, (400, 413))
        self.assertIn("error", error)
        self.assertEqual(self.documents(), [])

    def test_local_host_origin_and_mutation_token_are_enforced(self):
        payload = {"name": "blocked.txt", "content": base64.b64encode(b"fictional").decode("ascii")}
        for headers in ({}, {"X-Local-Token": "incorrect-token"}):
            with self.subTest(headers=headers):
                status, error = self.json_request("POST", "/api/upload", payload, headers)
                self.assertEqual(status, 403)
                self.assertIn("error", error)
        status, _ = self.json_request("GET", "/api/health", headers={"Host": "attacker.invalid"})
        self.assertEqual(status, 403)
        status, _ = self.json_request(
            "POST", "/api/upload", payload,
            {"X-Local-Token": self.server.token, "Origin": "https://attacker.invalid"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.documents(), [])

    def test_missing_resources_and_malformed_json_return_json_errors(self):
        for path in (
            "/api/does-not-exist",
            "/api/document-text?id=nonexistent-document",
            "/api/original?id=nonexistent-document",
        ):
            with self.subTest(path=path):
                status, error = self.json_request("GET", path)
                self.assertEqual(status, 404)
                self.assertIn("error", error)
        status, headers, body = self.request(
            "POST", "/api/upload", b'{"name":',
            {"Content-Type": "application/json", "X-Local-Token": self.server.token},
        )
        self.assertEqual(status, 400)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        self.assertIn("error", json.loads(body.decode("utf-8")))
        self.assertEqual(self.documents(), [])


if __name__ == "__main__":
    unittest.main()
