"""Token/position isolation of warm computation, using a checked in-memory ABI.

Real model quality, timing and no-egress remain separate native qualification.
"""

import ctypes as c

import pytest

from provelume.ai_llama import INT, Llama
from provelume.ai_models import ModelError


@pytest.fixture
def engine():
    engine = Llama.__new__(Llama)
    engine.vocab = engine.memory = engine.context = engine.sampler = None
    engine._prompt_tokens = ()
    engine._scope = None
    engine.next_tokens = ()
    engine.cells = []
    engine.decoded = []
    engine.removed = []
    engine.seen = []
    engine.refuse_removal = False
    engine.wrong_position = False

    def tokenize(vocab, raw, size, tokens, maximum, add_special, parse_special):
        for i, token in enumerate(engine.next_tokens):
            tokens[i] = token
        return len(engine.next_tokens)

    def clear(memory, data):
        assert data is True
        engine.cells.clear()

    def remove(memory, sequence, start, end):
        assert sequence == 0 and end == -1
        engine.removed.append(start)
        if engine.refuse_removal:
            return False
        del engine.cells[start:]
        return True

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

    engine.tokenize, engine.clear, engine.remove = tokenize, clear, remove
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
    ((1, 2, 8, 9), 2),  # Divergent private suffix, same public prefix.
    ((1, 2), 1),        # Shorter request removes the old longer suffix.
    ((5, 6, 7), 0),     # No shared prefix: full data/metadata clear.
    ((1, 2, 3, 4, 5), 4),  # Extension must exclude the previous generated token.
])
def test_warm_sequence_contains_only_current_input(engine, following, expected_reuse):
    assert generate(engine, (1, 2, 3, 4))["reused_input_tokens"] == 0
    assert engine.cells[-1] == 9001  # Old output really remains until next admission.
    engine.decoded.clear()
    result = generate(engine, following)
    assert result["reused_input_tokens"] == expected_reuse
    assert engine.seen[-1] == following
    assert engine.decoded[0] == following[expected_reuse:]


@pytest.mark.parametrize("failure", ["refuse_removal", "wrong_position"])
def test_invalid_native_truncation_stops_before_decode_or_output(engine, failure):
    generate(engine, (1, 2, 3, 4))
    setattr(engine, failure, True)
    engine.decoded.clear()
    emitted = []
    with pytest.raises(ModelError, match="state"):
        engine.generate("public synthetic input", emitted.append, scope="a" * 64)
    assert engine.decoded == [] and emitted == []


def test_maximum_prompt_keeps_one_bounded_sequence_across_batches(engine):
    tokens = tuple(range(1, 1537))
    generate(engine, tokens)
    assert [len(batch) for batch in engine.decoded] == [512, 512, 512, 1]
    following = (*tokens[:513], 7000, 7001)
    engine.decoded.clear()
    result = generate(engine, following)
    assert result["reused_input_tokens"] == 513
    assert engine.seen[-1] == following
    assert engine._prompt_tokens == following


@pytest.mark.parametrize("scope", [None, "b" * 64])
def test_other_instance_or_unscoped_qualification_cannot_reuse_governed_state(engine, scope):
    generate(engine, (1, 2, 3, 4))
    assert generate(engine, (1, 2, 3, 4), scope=scope)["reused_input_tokens"] == 0
    assert generate(engine, (1, 2, 3, 4))["reused_input_tokens"] == 0
