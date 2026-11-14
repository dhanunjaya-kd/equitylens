"""AI layer tests with the network mocked out:  python tests/test_ai.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("EQL_DATA_DIR", tempfile.mkdtemp())
os.environ["EQL_DEMO"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ai, service, store  # noqa: E402

store.init()


class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self._d


def _capture(provider, reply):
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        return FakeResp(reply)
    ai.requests.post = fake_post
    s = ai.load_settings() | {"provider": provider, "anthropic_api_key": "sk-ant-test", "openai_api_key": "sk-test",
                              "gemini_api_key": "AIza-test"}
    return calls, s


def test_context_has_core_data():
    rep = service.build_report("TESTCO")
    ctx = ai.build_context(rep)
    for k in ('"verdict"', '"forensics"', '"profit_loss"', '"fair_value"', '"Test Industries Ltd"'):
        assert k in ctx
    assert len(ctx) < 60000


def test_claude_request_shape():
    calls, s = _capture("claude", {"content": [{"type": "text", "text": "hello"}]})
    out = ai.complete("sys", [{"role": "user", "content": "q"}], 50, s)
    url, kw = calls[0]
    assert out == "hello" and url.endswith("/v1/messages")
    assert kw["headers"]["x-api-key"] == "sk-ant-test" and kw["headers"]["anthropic-version"] == "2023-06-01"
    assert kw["json"]["system"] == "sys" and kw["json"]["max_tokens"] == 50


def test_openai_request_shape():
    calls, s = _capture("openai", {"choices": [{"message": {"content": "hi"}}]})
    out = ai.complete("sys", [{"role": "user", "content": "q"}], 50, s)
    url, kw = calls[0]
    assert out == "hi" and url.endswith("/v1/chat/completions")
    assert kw["json"]["messages"][0] == {"role": "system", "content": "sys"}
    assert kw["json"]["max_completion_tokens"] == 50


def test_gemini_request_shape():
    calls, s = _capture("gemini", {"candidates": [{"content": {"parts": [{"text": "gem"}]}}]})
    out = ai.complete("sys", [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"},
                              {"role": "user", "content": "q2"}], 50, s)
    url, kw = calls[0]
    assert out == "gem" and url.endswith(":generateContent") and "/models/gemini" in url
    assert kw["headers"]["x-goog-api-key"] == "AIza-test"
    assert kw["json"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert [c["role"] for c in kw["json"]["contents"]] == ["user", "model", "user"]
    assert kw["json"]["generationConfig"]["maxOutputTokens"] == 50


def test_gemini_blocked_is_friendly():
    _, s = _capture("gemini", {"promptFeedback": {"blockReason": "SAFETY"}})
    try:
        ai.complete("s", [{"role": "user", "content": "q"}], 10, s)
        raise AssertionError("should fail")
    except ai.AIError as e:
        assert "SAFETY" in str(e)


def test_ollama_request_shape():
    calls, s = _capture("ollama", {"message": {"content": "local"}})
    assert ai.complete("sys", [{"role": "user", "content": "q"}], 50, s) == "local"
    assert calls[0][0].endswith("/api/chat") and calls[0][1]["json"]["stream"] is False


def test_error_message_is_friendly():
    def fake_post(url, **kw):
        return FakeResp({"error": {"message": "invalid x-api-key"}}, 401)
    ai.requests.post = fake_post
    s = ai.load_settings() | {"provider": "claude", "anthropic_api_key": "bad"}
    try:
        ai.complete("s", [{"role": "user", "content": "q"}], 10, s)
        raise AssertionError("should fail")
    except ai.AIError as e:
        assert "401" in str(e) and "key" in str(e)


def test_missing_key_blocks():
    s = ai.load_settings() | {"provider": "openai", "openai_api_key": ""}
    try:
        ai.complete("s", [{"role": "user", "content": "q"}], 10, s)
        raise AssertionError("should fail")
    except ai.AIError as e:
        assert "Settings" in str(e)


def test_settings_mask_and_keep_key():
    ai.save_settings({"provider": "claude", "anthropic_api_key": "sk-ant-api03-ABCDEFGHIJKLMNOP"})
    pub = ai.public_settings()
    assert "•" in pub["anthropic_api_key"] and "ABCDEFGH" not in pub["anthropic_api_key"]
    ai.save_settings({"provider": "openai", "anthropic_api_key": pub["anthropic_api_key"]})  # masked value sent back
    assert ai.load_settings()["anthropic_api_key"] == "sk-ant-api03-ABCDEFGHIJKLMNOP"
    ai.save_settings({"provider": "demo"})


def test_demo_features_end_to_end():
    rep = service.build_report("TESTCO")
    assert "In one paragraph" in ai.research_note(rep, None, refresh=True)["text"]
    d = ai.debate(rep, None, refresh=True)
    assert d["bull"] and d["bear"] and d["leaning"] == "Bull"
    assert ai.chat(rep, None, [{"role": "user", "content": "Is debt a worry?"}])["text"]
    assert "guidance" in ai.read_document(rep, "https://example.com/x.pdf", "Concall")["text"].lower()


def test_chart_outlook():
    from app import technicals
    t = technicals.build("TESTCO")
    o = t["outlook"]
    assert o["story"] and len(o["scenarios"]) == 3 and len(o["cone"]) == 3
    assert all(c["low80"] < t["c"][-1] < c["high80"] for c in o["cone"])
    assert o["analogs"] and all(a["count"] >= 20 for a in o["analogs"])
    assert o["cone_points"][0]["t"] > t["t"][-1]
    rep = service.build_report("TESTCO")
    assert ai.explain_chart(rep, t)["text"]


if __name__ == "__main__":
    import requests as _r
    orig = _r.post
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            ai.requests.post = orig
            f()
            print("PASS", k)
