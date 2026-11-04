"""Day 2 search behavior through HTTP, using fictional local documents only."""

import hashlib
import unittest
from urllib.parse import urlencode

import support


class SearchHTTPTests(support.HTTPFixture):
    def search(self, query, **options):
        parameters = {"q": query}
        parameters.update(options)
        return self.json_request("GET", "/api/search?" + urlencode(parameters))

    def add_document(self, text, name):
        status, response = self.upload(text.encode("utf-8"), name=name)
        self.assertEqual(status, 201)
        return response["document"]

    def test_chinese_and_case_insensitive_english_terms_must_share_one_chunk(self):
        document = self.add_document(
            "星河示例公司 CLOUD service 项目\n已提交虚构说明。\n\n"
            "星河单独出现。\n\ncloud 单独出现。\n",
            "mixed-language.md",
        )
        status, result = self.search("  星河   cLoUd  ")
        self.assertEqual(status, 200)
        self.assertEqual([term.lower() for term in result["terms"]], ["星河", "cloud"])
        self.assertEqual(result["total"], 1)
        self.assertIsNone(result["document_id"])
        self.assertEqual(result["results"][0]["document_id"], document["id"])
        self.assertEqual(result["results"][0]["start_line"], 1)
        self.assertEqual(result["results"][0]["end_line"], 2)
        self.assertEqual(result["results"][0]["excerpt"].splitlines()[0], "星河示例公司 CLOUD service 项目")

    def test_optional_document_filter_limits_results_to_the_selected_source(self):
        first = self.add_document("共享关键词，甲公司虚构说明。\n", "first.md")
        second = self.add_document("共享关键词，乙公司第一段。\n\n共享关键词，乙公司第二段。\n", "second.md")
        status, all_sources = self.search("共享关键词")
        self.assertEqual(status, 200)
        self.assertEqual(all_sources["total"], 3)
        status, filtered = self.search("共享关键词", document_id=second["id"])
        self.assertEqual(status, 200)
        self.assertEqual(filtered["document_id"], second["id"])
        self.assertEqual(filtered["total"], 2)
        self.assertEqual({row["document_id"] for row in filtered["results"]}, {second["id"]})
        self.assertNotIn(first["id"], {row["document_id"] for row in filtered["results"]})
        status, empty_filter = self.search("共享关键词", document_id="")
        self.assertEqual(status, 200)
        self.assertIsNone(empty_filter["document_id"])
        self.assertEqual(empty_filter["total"], 3)

    def test_percent_underscore_and_sql_like_input_are_literal_text(self):
        document = self.add_document(
            "Literal discount 50% on widget_code.\n\n"
            "Ordinary discount 500 on widgetXcode.\n\n"
            "Literal operator 'OR' documented.\n",
            "literal-symbols.txt",
        )
        for query in ("%", "_", "widget_code"):
            with self.subTest(query=query):
                status, result = self.search(query)
                self.assertEqual(status, 200)
                self.assertEqual(result["total"], 1)
                self.assertEqual(result["results"][0]["start_line"], 1)
                self.assertEqual(result["results"][0]["document_id"], document["id"])
        status, result = self.search("' OR 1=1 --")
        self.assertEqual(status, 200)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["results"], [])
        self.assertEqual(self.documents(), [document])

    def test_order_limits_totals_and_empty_results_are_consistent(self):
        older = self.add_document("marker old first\n\nmarker old second\n", "older.txt")
        newer = self.add_document("marker new first\n\nmarker new second\n\nmarker new third\n", "newer.txt")
        status, limited = self.search("marker", limit=2)
        self.assertEqual(status, 200)
        self.assertEqual(limited["limit"], 2)
        self.assertEqual(limited["total"], 5)
        self.assertIs(limited["has_more"], True)
        self.assertEqual(len(limited["results"]), 2)
        status, complete = self.search("marker", limit=50)
        self.assertEqual(status, 200)
        self.assertEqual(complete["limit"], 50)
        self.assertEqual(complete["total"], 5)
        self.assertIs(complete["has_more"], False)
        self.assertEqual(len(complete["results"]), 5)
        self.assertEqual(limited["results"], complete["results"][:2])
        dates = {doc["id"]: doc["created_at"] for doc in (older, newer)}
        result_dates = [dates[row["document_id"]] for row in complete["results"]]
        self.assertEqual(result_dates, sorted(result_dates, reverse=True))
        for document in (older, newer):
            positions = [row["position"] for row in complete["results"] if row["document_id"] == document["id"]]
            self.assertEqual(positions, sorted(positions))
        status, missing = self.search("nothing-matches-this-query")
        self.assertEqual(status, 200)
        self.assertEqual(missing["limit"], 20)
        self.assertEqual(missing["total"], 0)
        self.assertIs(missing["has_more"], False)
        self.assertEqual(missing["results"], [])

    def test_search_result_links_to_the_original_chunk_and_uses_a_source_excerpt(self):
        paragraph = "前置说明" * 90 + "检索锚点" + "后续资料" * 90
        raw = b"\xef\xbb\xbf" + ("虚构来源首段\r\n\r\n" + paragraph + "\r\n同一段下一行\r\n").encode("utf-8")
        status, uploaded = self.upload(raw, name="source-lines.txt")
        self.assertEqual(status, 201)
        document = uploaded["document"]
        status, detail = self.json_request("GET", self.document_path("/api/document-text", document))
        self.assertEqual(status, 200)
        status, result = self.search("检索锚点")
        self.assertEqual(status, 200)
        self.assertEqual(result["total"], 1)
        row = result["results"][0]
        fields = {"chunk_id", "document_id", "title", "filename", "sha256", "position", "start_line", "end_line", "location", "excerpt"}
        self.assertTrue(fields.issubset(row))
        chunk = next(chunk for chunk in detail["chunks"] if chunk["id"] == row["chunk_id"])
        self.assertEqual((row["start_line"], row["end_line"]), (3, 4))
        for field in ("position", "start_line", "end_line", "location"):
            self.assertEqual(row[field], chunk[field])
        for field in ("title", "filename", "sha256"):
            self.assertEqual(row[field], document[field])
        self.assertLessEqual(len(row["excerpt"]), 242)
        self.assertIn("检索锚点", row["excerpt"])
        source_fragment = row["excerpt"].strip("…").removeprefix("...").removesuffix("...")
        self.assertTrue(source_fragment)
        self.assertIn(source_fragment, chunk["content"])

    def test_invalid_queries_limits_and_unknown_sources_report_errors(self):
        invalid_parameters = [
            {},
            {"q": ""},
            {"q": "   \t "},
            {"q": "a" * 201},
            {"q": "one two three four five six seven eight nine"},
        ]
        invalid_parameters.extend({"q": "fictional", "limit": value} for value in ("", "0", "-1", "51", "1.5", "abc"))
        for parameters in invalid_parameters:
            with self.subTest(parameters=parameters):
                status, error = self.json_request("GET", "/api/search?" + urlencode(parameters))
                self.assertEqual(status, 400)
                self.assertIn("error", error)
        status, error = self.search("fictional", document_id="nonexistent-document")
        self.assertEqual(status, 404)
        self.assertIn("error", error)
        self.add_document("a" * 201, "query-boundary.txt")
        status, result = self.search("a" * 200, limit=1)
        self.assertEqual(status, 200)
        self.assertEqual(result["total"], 1)

    def test_search_survives_restart_and_does_not_modify_imported_evidence(self):
        raw = b"\xef\xbb\xbfFictional archived evidence.\r\n\r\nPersistent marker.\r\n"
        status, uploaded = self.upload(raw, name="archived.txt")
        self.assertEqual(status, 201)
        document = uploaded["document"]
        status, before = self.json_request("GET", self.document_path("/api/document-text", document))
        self.assertEqual(status, 200)
        status, initial_search = self.search("persistent")
        self.assertEqual(status, 200)
        self.stop_server()
        self.start_server()
        status, restored_search = self.search("persistent")
        self.assertEqual(status, 200)
        self.assertEqual(restored_search, initial_search)
        self.assertEqual(restored_search["total"], 1)
        self.assertEqual(self.documents(), [document])
        status, after = self.json_request("GET", self.document_path("/api/document-text", document))
        self.assertEqual(status, 200)
        self.assertEqual(after, before)
        status, _, original = self.request("GET", self.document_path("/api/original", document))
        self.assertEqual(status, 200)
        self.assertEqual(original, raw)
        self.assertEqual(hashlib.sha256(original).hexdigest(), document["sha256"])

    def test_duplicate_import_does_not_duplicate_results_or_change_chunk_ids(self):
        raw = b"Duplicate marker first.\n\nDuplicate marker second.\n"
        status, original = self.upload(raw, name="initial-name.md")
        self.assertEqual(status, 201)
        status, before = self.search("duplicate marker")
        self.assertEqual(status, 200)
        self.assertEqual(before["total"], 2)
        status, repeated = self.upload(raw, name="another-name.md")
        self.assertEqual(status, 200)
        self.assertIs(repeated["duplicate"], True)
        self.assertEqual(repeated["document"], original["document"])
        status, after = self.search("duplicate marker")
        self.assertEqual(status, 200)
        self.assertEqual(after, before)
        self.assertEqual(len({row["chunk_id"] for row in after["results"]}), 2)
        self.assertEqual(self.documents(), [original["document"]])


if __name__ == "__main__":
    unittest.main()
