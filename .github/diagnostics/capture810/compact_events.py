"""Generate and independently decode an event-preserving compact BPF stream."""

from __future__ import annotations

import hashlib
import re
from collections import Counter

MAX_BYTES = 2 * 1024 * 1024
MAX_DELTA = 1 << 36
BASE = 33
MAX_RELATIVE_TID = 127
KINDS = {
    "F": (1, 4),
    "S": (2, 5),
    "W": (3, 3),
    "M": (4, 4),
    "U": (5, 4),
    "D": (6, 4),
    "X": (7, 3),
    "T": (8, 4),
}
STATES = (0, 1, 2, 8, 128, 256, 4, 32)
SINGLE = (("W", None), ("U", 1), ("U", 0), ("D", 1), ("D", 0))
PACKED_IDS = frozenset((2, 3, 5, 6))
HEADER = re.compile(r"C810v1 (\d+) (\d+)")
COUNT = re.compile(r"@(emitted|packed)\[(\d+)\]: (\d+)")
LEGACY = re.compile(r"[FSWMUDXT](?: \d+)+")
SOURCE_SHA256 = "d0c107cf4db1360047ee6f8a84ace3a76cefb22ff93e0bf93da2c7ff221d8474"


def printable(word, length):
    return "".join(chr(BASE + ((word >> shift) & 63)) for shift in range(6 * (length - 1), -1, -6))


def marked_word(word, length):
    text = "%c" * length
    arguments = ", ".join(
        f"(33 + (($encoded >> {shift}) & 63))" for shift in range(6 * (length - 1), -1, -6)
    )
    return f'$encoded = (uint64)({word}); printf("{text}\\n", {arguments});'


def numeric_row(row):
    return " ".join(str(value) for value in row)


def encode_row(row, epoch, cpid):
    delta = row[1] - epoch
    if not 0 <= delta < MAX_DELTA:
        return numeric_row(row), False
    kind = row[0]
    if kind == "S" and row[4] in STATES:
        prev, following = row[2:4]
        state = STATES.index(row[4])
        if prev and following:
            left, right = prev - cpid, following - cpid
            if all(0 <= relative <= MAX_RELATIVE_TID for relative in (left, right)):
                word = (delta << 19) | (left << 12) | (right << 5) | (state << 2) | 3
                return printable(word, 10), True
        elif prev or following:
            relative = (prev or following) - cpid
            if 0 <= relative <= MAX_RELATIVE_TID:
                word = (delta << 12) | (relative << 5) | (state << 2) | (1 if prev else 2)
                return printable(word, 8), True
    elif kind in ("W", "U", "D"):
        flag = None if kind == "W" else row[3]
        relative = row[2] - cpid
        if 0 <= relative <= MAX_RELATIVE_TID and (kind, flag) in SINGLE:
            word = (delta << 12) | (relative << 5) | (SINGLE.index((kind, flag)) << 2)
            return printable(word, 8), True
    return numeric_row(row), False


def decode_row(line, epoch, cpid):
    if LEGACY.fullmatch(line):
        parts = line.split(" ")
        kind = parts[0]
        if len(parts) != KINDS[kind][1]:
            raise ValueError("Wrong uncompressed field count")
        return (kind, *map(int, parts[1:])), False
    if len(line) not in (8, 10) or any(not BASE <= ord(symbol) < BASE + 64 for symbol in line):
        raise ValueError("Invalid compact event")
    word = 0
    for symbol in line:
        word = (word << 6) | (ord(symbol) - BASE)
    code = word & 3
    state_or_subtype = (word >> 2) & 7
    if len(line) == 10:
        if code != 3 or word >> 55:
            raise ValueError("Invalid two-task switch")
        first, second = (word >> 12) & 127, (word >> 5) & 127
        return (
            "S",
            epoch + (word >> 19),
            cpid + first,
            cpid + second,
            STATES[state_or_subtype],
        ), True
    stamp, tid = epoch + (word >> 12), cpid + ((word >> 5) & 127)
    if code == 0 and state_or_subtype < len(SINGLE):
        kind, flag = SINGLE[state_or_subtype]
        return (kind, stamp, tid) if flag is None else (kind, stamp, tid, flag), True
    if code in (1, 2):
        return (
            "S",
            stamp,
            tid if code == 1 else 0,
            tid if code == 2 else 0,
            STATES[state_or_subtype],
        ), True
    raise ValueError("Invalid one-task event")


def decode_stream(raw, stderr=b""):
    """Check original size and independent kernel totals before using any event."""
    if len(raw) > MAX_BYTES or stderr.strip():
        raise ValueError("Oversized stream or observer diagnostic")
    lines = raw.decode("ascii").split("\n")
    headers = [match for line in lines if (match := HEADER.fullmatch(line))]
    if len(headers) != 1:
        raise ValueError("Missing or duplicate encoding header")
    epoch, cpid = map(int, headers[0].groups())
    if not 0 < epoch < 1 << 64 or not 0 < cpid < 1 << 22:
        raise ValueError("Invalid boot epoch or collector PID")
    totals, totals_packed = {}, {}
    observed, observed_packed, rows = Counter(), Counter(), []
    for line in lines:
        if not line or HEADER.fullmatch(line):
            continue
        if match := COUNT.fullmatch(line):
            name, key, value = match.groups()
            key, value = int(key), int(value)
            table = totals if name == "emitted" else totals_packed
            allowed = (
                {meaning[0] for meaning in KINDS.values()} if name == "emitted" else PACKED_IDS
            )
            if key not in allowed or key in table or value <= 0:
                raise ValueError("Invalid or duplicate kernel counter")
            table[key] = value
            continue
        row, packed = decode_row(line, epoch, cpid)
        if row[1] < epoch or any(value >= 1 << 64 for value in row[1:]):
            raise ValueError("Event outside original clock or integer range")
        kind_id = KINDS[row[0]][0]
        rows.append(list(row))
        observed[kind_id] += 1
        if packed:
            observed_packed[kind_id] += 1
    if not rows or dict(observed) != totals or dict(observed_packed) != totals_packed:
        raise ValueError("Kernel counts do not match decoded events")
    return sorted(rows, key=lambda row: row[1]), {
        "events": totals,
        "packed": totals_packed,
        "bytes": len(raw),
    }


def single_statement(kind, stamp, tid, sub, original):
    event_id = KINDS[kind][0]
    return f"""
  $mark_stamp = (uint64)({stamp});
  $tick = (uint64)($mark_stamp - @compact_epoch);
  $relative = (int64)({tid}) - (int64)cpid;
  if ($tick < {MAX_DELTA} && $relative >= 0 && $relative <= {MAX_RELATIVE_TID}) {{
    @packed[{event_id}] = count();
    {marked_word(f"($tick << 12) | ((uint64)$relative << 5) | {sub << 2}", 8)}
  }} else {{
    {original}
  }}
""".strip()


def build_program(original):
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("Original observer bytes are unavailable")
    code = original.decode("ascii")

    def replace_once(before, after):
        nonlocal code
        if code.count(before) != 1:
            raise ValueError("Observer emission shape changed")
        code = code.replace(before, after)

    replace_once(
        "BEGIN { @owned[cpid] = 1; @active = 0; }",
        """BEGIN {
  @owned[cpid] = 1; @active = 0;
  @compact_epoch = nsecs;
  printf("C810v1 %llu %d\\n", @compact_epoch, cpid);
}""",
    )
    old_switch = """printf("S %llu %d %d %d\\n", nsecs,
    @owned[args.prev_pid] ? args.prev_pid : 0,
    @owned[args.next_pid] ? args.next_pid : 0, args.prev_state);"""
    known_states = " ".join(
        f"if (args.prev_state == {state}) {{ $state_code = {i}; }}"
        for i, state in enumerate(STATES)
    )
    packed_two_task = marked_word(
        "($tick << 19) | ((uint64)$a << 12) | ((uint64)$b << 5) | ($state_code << 2) | 3",
        10,
    )
    replace_once(
        old_switch,
        f"""$switch_ns = nsecs;
  $tick = (uint64)($switch_ns - @compact_epoch);
  $left = @owned[args.prev_pid] ? args.prev_pid : 0;
  $right = @owned[args.next_pid] ? args.next_pid : 0;
  $a = (int64)$left - (int64)cpid;
  $b = (int64)$right - (int64)cpid;
  $state_code = 8;
  {known_states}
  if ($tick < {MAX_DELTA} && $state_code < 8 && ($left || $right) &&
      (!$left || ($a >= 0 && $a <= 127)) && (!$right || ($b >= 0 && $b <= 127))) {{
    @packed[2] = count();
    if ($left && $right) {{
      {packed_two_task}
    }} else {{
      $relative = $left ? $a : $b;
      $code = $left ? 1 : 2;
      {marked_word("($tick << 12) | ((uint64)$relative << 5) | ($state_code << 2) | $code", 8)}
    }}
  }} else {{
    printf("S %llu %d %d %d\\n", $switch_ns, $left, $right, args.prev_state);
  }}""",
    )
    wake = 'printf("W %llu %d\\n", nsecs, args.pid);'
    replace_once(
        wake, single_statement("W", "nsecs", "args.pid", 0, wake.replace("nsecs", "$mark_stamp"))
    )
    for kind, name, flags in (("U", "futex", (1, 2)), ("D", "fsync", (3, 4))):
        stamp = f"@{name}_start[tid]"
        start = f'printf("{kind} %llu %d 1\\n", {stamp}, tid);'
        end = f'printf("{kind} %llu %d 0\\n", nsecs, tid);'
        if code.count(start) != 2:
            raise ValueError("Original syscall boundary emission changed")
        code = code.replace(
            start,
            single_statement(kind, stamp, "tid", flags[0], start.replace(stamp, "$mark_stamp")),
        )
        replace_once(
            end,
            single_statement(kind, "nsecs", "tid", flags[1], end.replace("nsecs", "$mark_stamp")),
        )
    replace_once(
        "  clear(@owned); clear(@active);",
        "  clear(@owned); clear(@active); clear(@compact_epoch);",
    )
    return code.encode("ascii")
