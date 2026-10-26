"""覆盖真实风险：摘要外发、公开/内部目标混用以及跨仓库 SHA 冲突。"""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from org_readme_gen import cli, github
from org_readme_gen.config import load_config
from org_readme_gen.models import LlmConfig, OrgConfig, RepoInfo


def repo(name, private=False):
    return RepoInfo(name, "", f"https://github.com/example/{name}", "Python", 0, [], False, False, private=private)


class AudienceFlowTests(unittest.TestCase):
    def run_flow(self, audience, dry_run=False):
        public, private = repo("public"), repo("secret", True)
        with (
            patch.object(cli, "get_org_repos", return_value=[public, private, repo(".github"), repo(".github-private", True)]),
            patch.object(cli, "get_repo_readme", return_value="excerpt") as summaries,
            patch.object(cli, "get_org_readme", return_value=("existing", "target-sha")) as read,
            patch.object(cli, "generate_readme", return_value="# iugam") as generate,
            patch.object(cli, "ensure_github_repo") as ensure,
            patch.object(cli, "update_readme", return_value="commit") as write,
        ):
            cli._process_org(OrgConfig("example", audience=audience, output_branch="master"), LlmConfig(), dry_run)
        return summaries, read, generate, ensure, write

    def test_public_excludes_private_before_summaries_and_llm(self):
        summaries, read, generate, ensure, write = self.run_flow("public")
        self.assertEqual([c.args[1] for c in summaries.call_args_list], ["public"])
        self.assertEqual([r.name for r in generate.call_args.args[2]], ["public"])
        read.assert_called_once_with("example", "public", "master")
        ensure.assert_called_once_with("example", ".github")
        self.assertEqual(write.call_args.kwargs["sha"], "target-sha")
        self.assertEqual(write.call_args.kwargs["audience"], "public")

    def test_internal_reads_and_writes_private_target(self):
        summaries, read, generate, ensure, write = self.run_flow("internal")
        self.assertEqual([c.args[1] for c in summaries.call_args_list], ["public", "secret"])
        self.assertEqual([r.name for r in generate.call_args.args[2]], ["public", "secret"])
        read.assert_called_once_with("example", "internal", "master")
        ensure.assert_called_once_with("example", ".github-private")
        self.assertEqual(write.call_args.kwargs["audience"], "internal")

    def test_dry_run_never_creates_or_updates(self):
        *_, ensure, write = self.run_flow("internal", True)
        ensure.assert_not_called()
        write.assert_not_called()

    def test_invalid_audience_rejected_before_network(self):
        with patch.object(cli, "get_org_repos") as get:
            with self.assertRaises(ValueError):
                cli._process_org(OrgConfig("example", audience="typo"), LlmConfig(), False)
            get.assert_not_called()

    def test_unknown_visibility_defaults_to_private(self):
        self.assertTrue(RepoInfo("x", "", "", "", 0, [], False, False).private)

    def test_invalid_config_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text("orgs:\n  - name: example\n    audience: typo\n")
            with self.assertRaises(ValueError):
                load_config(config)


class GithubTargetTests(unittest.TestCase):
    def setUp(self):
        self.real_client = httpx.Client
        self.requests = []
        self.headers = patch.object(github, "_headers", return_value={})
        self.headers.start()
        self.addCleanup(self.headers.stop)

    def transport(self, handler):
        def handle(request):
            self.requests.append(request)
            return handler(request)
        return patch.object(github.httpx, "Client", side_effect=lambda **kw: self.real_client(transport=httpx.MockTransport(handle), **kw))

    def test_each_audience_reads_only_its_target_branch(self):
        for audience, target in [("public", ".github"), ("internal", ".github-private")]:
            with self.subTest(audience=audience):
                with self.transport(lambda r: httpx.Response(200, json={"content": base64.b64encode(target.encode()).decode(), "sha": target+"-sha"})):
                    self.assertEqual(github.get_org_readme("example", audience, "master"), (target, target+"-sha"))
                req = self.requests[-1]
                self.assertIn(f"/example/{target}/contents/", req.url.path)
                self.assertEqual(req.url.params["ref"], "master")

    def test_missing_public_readme_does_not_fallback_to_private(self):
        with self.transport(lambda r: httpx.Response(404)):
            self.assertIsNone(github.get_org_readme("example"))
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn(".github-private", str(self.requests[0].url))

    def test_read_permission_failure_is_not_treated_as_missing(self):
        with self.transport(lambda r: httpx.Response(403)):
            with self.assertRaises(httpx.HTTPStatusError):
                github.get_org_readme("example")

    def test_internal_update_fetches_sha_from_same_branch_and_repo(self):
        def handle(request):
            if request.method == "GET":
                return httpx.Response(200, json={"sha": "private-master-sha"})
            body = json.loads(request.content)
            self.assertEqual(body["sha"], "private-master-sha")
            self.assertEqual(body["branch"], "master")
            return httpx.Response(200, json={"commit": {"html_url": "commit"}})
        with self.transport(handle):
            self.assertEqual(github.update_readme("example", "text", None, "master", "docs", "internal"), "commit")
        self.assertEqual(self.requests[0].url.path, self.requests[1].url.path)
        self.assertIn("/.github-private/", self.requests[0].url.path)
        self.assertEqual(self.requests[0].url.params["ref"], "master")

    def test_write_keeps_provided_target_sha(self):
        with self.transport(lambda r: httpx.Response(200, json={"commit": {}})):
            github.update_readme("example", "text", "public-sha", "main", "docs")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(json.loads(self.requests[0].content)["sha"], "public-sha")
        self.assertIn("/.github/", self.requests[0].url.path)

    def test_internal_repo_created_private(self):
        def handle(request):
            if request.method == "GET":
                return httpx.Response(404)
            self.assertIs(json.loads(request.content)["private"], True)
            return httpx.Response(201, json={})
        with self.transport(handle):
            github.ensure_github_repo("example", ".github-private")

    def test_internal_repo_cannot_already_be_public(self):
        with self.transport(lambda r: httpx.Response(200, json={"private": False})):
            with self.assertRaises(RuntimeError):
                github.ensure_github_repo("example", ".github-private")

    def test_graphql_reads_visibility_across_pages(self):
        def handle(request):
            payload = json.loads(request.content)
            self.assertIn("isPrivate", payload["query"])
            second = payload["variables"].get("after") == "cursor"
            node = {"name": "secret" if second else "public", "url": "url", "isPrivate": second}
            return httpx.Response(200, json={"data": {"organization": {"repositories": {
                "nodes": [node], "pageInfo": {"hasNextPage": not second, "endCursor": "cursor"},
            }}}})
        with self.transport(handle):
            repos = github.get_org_repos("example")
        self.assertEqual([r.private for r in repos], [False, True])


if __name__ == "__main__":
    unittest.main()
