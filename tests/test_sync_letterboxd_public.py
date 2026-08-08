from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_letterboxd_public.py"
SPEC = importlib.util.spec_from_file_location("sync_letterboxd_public", SCRIPT_PATH)
assert SPEC and SPEC.loader
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str = "ok",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls = 0

    def get(self, *args: object, **kwargs: object) -> FakeResponse:
        response = self.responses[self.calls]
        self.calls += 1
        return response


class FetchTextTests(unittest.TestCase):
    def test_cloudflare_challenge_is_not_retried(self) -> None:
        session = FakeSession(
            [FakeResponse(status_code=403, headers={"cf-mitigated": "challenge"})]
        )

        with patch.object(sync, "get_session", return_value=session):
            with self.assertRaises(sync.LetterboxdChallengeError):
                sync.fetch_text("/goorison/diary/films/")

        self.assertEqual(session.calls, 1)

    def test_regular_failure_still_retries_and_fails(self) -> None:
        session = FakeSession([FakeResponse(status_code=500) for _ in range(3)])

        with (
            patch.object(sync, "get_session", return_value=session),
            patch.object(sync.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
                sync.fetch_text("/goorison/diary/films/")

        self.assertEqual(session.calls, 3)

    def test_cli_uses_distinct_exit_code_for_cloudflare_challenge(self) -> None:
        error = sync.LetterboxdChallengeError("challenge")

        with (
            patch.object(sync, "main", side_effect=error),
            patch.object(sync.sys, "stderr", new_callable=io.StringIO) as stderr,
        ):
            status = sync.run()

        self.assertEqual(status, 75)
        self.assertIn("leaving the published report unchanged", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
