import threading

from abhelper.agent.conversation import Conversation, ConversationStore


def msgs(n_exchanges):
    out = []
    for i in range(n_exchanges):
        out += [{"role": "user", "content": f"q{i}"},
                {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "{}"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "a"}]}]
    return out


def test_trim_cuts_on_exchange_boundary():
    c = Conversation(messages=msgs(30))  # 120 messages
    c.trim(max_messages=50)
    assert len(c.messages) <= 50
    assert c.messages[0]["role"] == "user" and isinstance(c.messages[0]["content"], str)
    # no orphan tool_result at the start
    ids_use = {b["id"] for m in c.messages if m["role"] == "assistant" for b in m["content"] if b["type"] == "tool_use"}
    ids_res = {b["tool_use_id"] for m in c.messages if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"]}
    assert ids_use == ids_res


def test_trim_noop_when_short():
    c = Conversation(messages=msgs(2))
    c.trim()
    assert len(c.messages) == 8


def test_store_get_reset_evict():
    s = ConversationStore(max_conversations=3)
    a = s.get("a")
    assert s.get("a") is a
    assert s.get(None).id != "a"
    for i in range(5):
        s.get(f"c{i}")
    assert len(s) == 3
    assert s.reset("c4") and not s.reset("zzz")
    assert s.get("nope", create=False) is None


def test_busy_lock():
    c = Conversation()
    assert c.try_begin() and not c.try_begin()
    c.end()
    assert c.try_begin()


def test_store_thread_safety():
    s = ConversationStore()
    ids = []

    def work():
        ids.append(s.get(None).id)

    ts = [threading.Thread(target=work) for _ in range(50)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(set(ids)) == 50
