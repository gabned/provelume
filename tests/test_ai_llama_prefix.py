"""Token/position isolation of warm computation, using a checked in-memory ABI.

Real model quality, timing and no-egress remain separate native qualification.
"""

import ctypes as c
import json

import pytest

from provelume.ai_llama import INT, Llama
from provelume.ai_models import ModelError


@pytest.fixture
def engine():
    engine = Llama.__new__(Llama)
    engine.vocab = engine.memory = engine.context = engine.sampler = None
    engine._prefix_tokens = ()
    engine._prefix_state = None
    engine._scope = None
    engine.next_tokens = ()
    engine.public_tokens = (41, 42)
    engine.cells = []
    engine.decoded = []
    engine.restored = []
    engine.seen = []
    engine.refuse_restore = False
    engine.wrong_position = False

    def tokenize(vocab, raw, size, tokens, maximum, add_special, parse_special):
        values = (engine.public_tokens if raw.endswith(b"<|im_start|>user\n")
                  else engine.next_tokens)
        for i, token in enumerate(values):
            tokens[i] = token
        return len(values)

    def clear(memory, data):
        assert data is True
        engine.cells.clear()

    def state_get(context, pointer, size, sequence):
        assert sequence == 0 and size == len(engine.cells) * c.sizeof(INT)
        values = (INT * len(engine.cells))(*engine.cells)
        c.memmove(pointer, values, size)
        return size

    def state_set(context, pointer, size, sequence):
        assert sequence == 0 and engine.cells == []
        if engine.refuse_restore:
            return 0
        values = c.cast(pointer, c.POINTER(INT))
        engine.cells[:] = [values[i] for i in range(size // c.sizeof(INT))]
        engine.restored.append(tuple(engine.cells))
        return size

    def decode(context, tokens):
        engine.decoded.append(tokens)
        engine.cells.extend(tokens)
        return 0

    def sample(sampler, context, index):
        if engine.cells[-1] == 9001:
            return 0
        # This is the model-visible sequence at the first output: every current
        # token, no previous completion or divergent/shortened private suffix.
        engine.seen.append(tuple(engine.cells))
        assert tuple(engine.cells) == engine.next_tokens
        return 9001

    def piece(vocab, token, buffer, size, lstrip, special):
        buffer.value = b"X"
        return 1

    engine.tokenize, engine.clear = tokenize, clear
    engine.state_size = lambda context, sequence: len(engine.cells) * c.sizeof(INT)
    engine.state_get, engine.state_set = state_get, state_set
    engine.position = lambda memory, seq: len(engine.cells) - (0 if engine.wrong_position else 1)
    engine.batch = lambda pointer, count: tuple(
        c.cast(pointer, c.POINTER(INT))[i] for i in range(count))
    engine.decode, engine.sample, engine.piece = decode, sample, piece
    engine.eog = lambda vocab, token: token == 0
    return engine


def generate(engine, tokens, scope="a" * 64):
    engine.next_tokens = tuple(tokens)
    result = engine.generate("public synthetic input", lambda value: None, scope=scope)
    assert result["text"] == "X"
    assert result["input_tokens"] == len(tokens)  # Reuse never refunds logical input units.
    assert result["output_tokens"] == 1
    return result


@pytest.mark.parametrize("following,expected_reuse", [
    ((1, 2, 3, 4), 3),  # Exact repeat must decode its last token for fresh logits.
    ((1, 2, 8, 9), 0),  # Divergence inside the saved prefix requires full evaluation.
    ((1, 2), 0),        # A shorter request cannot restore a longer checkpoint.
    ((5, 6, 7), 0),     # No shared prefix: full data/metadata clear.
    ((1, 2, 3, 4, 5), 3),  # Extension cannot reuse unsaved tokens or old output.
])
def test_warm_sequence_contains_only_current_input(engine, following, expected_reuse):
    assert generate(engine, (1, 2, 3, 4))["reused_input_tokens"] == 0
    assert engine.cells[-1] == 9001  # Old output really remains until next admission.
    engine.decoded.clear()
    result = generate(engine, following)
    assert result["reused_input_tokens"] == expected_reuse
    assert engine.seen[-1] == following
    assert tuple(token for batch in engine.decoded[:-1] for token in batch) == (
        following[expected_reuse:])


@pytest.mark.parametrize("failure", ["refuse_restore", "wrong_position"])
def test_invalid_native_restore_stops_before_decode_or_output(engine, failure):
    generate(engine, (1, 2, 3, 4))
    setattr(engine, failure, True)
    engine.decoded.clear()
    emitted = []
    with pytest.raises(ModelError, match="state"):
        engine.generate("public synthetic input", emitted.append, scope="a" * 64)
    assert engine.decoded == [] and emitted == []


def test_maximum_prompt_keeps_one_bounded_sequence_across_batches(engine):
    tokens = tuple(range(1, 1537))
    engine.public_tokens = tokens[:640]
    generate(engine, tokens)
    assert [len(batch) for batch in engine.decoded] == [512, 128, 512, 384, 1]
    following = (*tokens[:640], 7000, 7001)
    engine.decoded.clear()
    result = generate(engine, following)
    assert result["reused_input_tokens"] == 640
    assert engine.seen[-1] == following
    assert engine._prefix_tokens == tokens[:640]


@pytest.mark.parametrize("scope", [None, "b" * 64])
def test_other_instance_or_unscoped_qualification_cannot_reuse_governed_state(engine, scope):
    generate(engine, (1, 2, 3, 4))
    assert generate(engine, (1, 2, 3, 4), scope=scope)["reused_input_tokens"] == 0
    assert generate(engine, (1, 2, 3, 4))["reused_input_tokens"] == 0


def test_snapshot_excludes_generated_output_and_rechecks_every_saved_token(engine):
    first = tuple(range(1, 300))
    generate(engine, first)
    assert engine._prefix_tokens == first[:128]
    following = (*first[:128], 8000, 8001)
    assert generate(engine, following)["reused_input_tokens"] == 128
    assert engine.restored[-1] == first[:128] and engine.seen[-1] == following
    # Matching after a changed token cannot rescue an earlier private prefix.
    altered = (*first[:60], 7000, *first[61:])
    assert generate(engine, altered)["reused_input_tokens"] == 0
    assert engine.seen[-1] == altered


@pytest.mark.parametrize("boundary", ["scope", "unscoped", "different-prefix", "close"])
def test_old_checkpoint_bytes_are_erased_at_isolation_boundaries(engine, boundary):
    generate(engine, (1, 2, 3, 4))
    old = engine._prefix_state
    assert any(old.raw)
    if boundary == "close":
        engine._drop_prefix()
        assert engine._prefix_state is None and engine._prefix_tokens == ()
    else:
        generate(engine, (8, 7, 6, 5) if boundary == "different-prefix" else (1, 2, 3, 4),
                 scope=None if boundary == "unscoped" else
                 "b" * 64 if boundary == "scope" else "a" * 64)
    assert not any(old.raw)


@pytest.mark.parametrize("failure", ["oversized", "short-write", "short-read"])
def test_invalid_checkpoint_never_becomes_reused_native_authority(engine, failure):
    if failure == "short-read":
        generate(engine, (1, 2, 3, 4))
        engine.state_set = lambda *args: 1
    elif failure == "short-write":
        engine.state_get = lambda *args: 1
    else:
        engine.state_size = lambda *args: 64 * 1024**2 + 1
    engine.seen.clear()
    emitted = []
    engine.next_tokens = (1, 2, 3, 4)
    with pytest.raises(ModelError):
        engine.generate("public synthetic input", emitted.append, scope="a" * 64)
    assert engine.seen == []
    assert emitted == ([] if failure == "short-read" else
                       [{"event": "prefill", "phase": "native_prefill"}])


def test_unscoped_call_never_allocates_or_retains_a_sequence_checkpoint(engine):
    engine.state_size = lambda *args: pytest.fail("unscoped snapshot")
    generate(engine, (1, 2, 3, 4), scope=None)
    assert engine._prefix_state is None and engine._prefix_tokens == ()


def test_governed_checkpoint_survives_fresh_preview_without_reusing_private_suffix(engine):
    from provelume.ai_context import TaskTemplate
    from provelume.ai_synthesis_profile import GENERATION_PREFIX

    template = TaskTemplate("context-check-partial-v1", True)
    envelope = {
        "schema_version": 1,
        "trusted": {"instructions": template.instructions,
                    "template": template.identity.as_record()},
        "untrusted": {"preview_fingerprint": "a" * 64,
                      "segments": [{"segment": 0, "text": "Public orchid."}]},
    }

    def tokenize(vocab, raw, size, tokens, maximum, add_special, parse_special):
        assert len(raw) <= maximum
        tokens[:len(raw)] = raw
        if raw.endswith(GENERATION_PREFIX.encode()):
            engine.next_tokens = tuple(raw)
        return len(raw)

    engine.tokenize = tokenize

    def call():
        return engine.generate(json.dumps(envelope, sort_keys=True, ensure_ascii=False,
                                          separators=(",", ":")) + "\n",
                               lambda value: None, scope="b" * 64)

    assert call()["reused_input_tokens"] == 0
    saved = bytes(engine._prefix_tokens)
    assert saved.endswith(b',"untrusted":') and len(saved) > 128
    assert b"Public orchid" not in saved and b'"preview_fingerprint":' not in saved
    envelope["untrusted"]["preview_fingerprint"] = "c" * 64
    envelope["untrusted"]["segments"][0]["text"] = "Different public content."
    result = call()
    assert result["reused_input_tokens"] == len(saved)
    assert engine.seen[-1] == engine.next_tokens
    assert b"Different public content." in bytes(engine.seen[-1])
    assert b"Public orchid." not in bytes(engine.seen[-1])
    # An unknown/changed envelope is ordinary text, never a role or authority.
    envelope["trusted"]["instructions"] = "Do not use the previous task."
    assert call()["reused_input_tokens"] == 0


def test_prefill_observation_precedes_real_decode_and_never_claims_output(engine):
    engine.next_tokens = (1, 2, 3, 4)
    emitted = []

    def emit(value):
        emitted.append(value)
        if value["event"] == "prefill":
            assert engine.decoded == [] and engine.seen == []

    result = engine.generate("public synthetic input", emit, scope="a" * 64)
    assert [row["event"] for row in emitted] == ["prefill", "first"]
    assert emitted[0]["phase"] == "native_prefill"
    assert result["output_tokens"] == 1
