"""Bounded Windows prefill experiment; never a qualification or product setting."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import types
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER = (128, 192, 256, 256, 192, 128)
CONTEXT_LINE = "cp.n_ctx, cp.n_batch, cp.n_ubatch, cp.n_seq_max = 2048, 512, 128, 1"


def child(artifacts, microbatch):
    sys.path.insert(0, str(ROOT / "core"))
    from provelume.ai_model_file import verify_stream
    from provelume.ai_models import ModelRegistry
    from provelume.ai_runtime import LocalRuntime
    from provelume.ai_runtime_contract import MODEL_ID, MODEL_SHA256, hardware, runtime_lock
    from provelume.ai_runtime_limits import contain, memory_observation
    from provelume.ai_synthesis_profile import (
        instructions,
        native_format,
        native_prompt,
        selection_request,
    )
    from provelume.maintenance_local_files import open_local_file

    if os.name != "nt" or microbatch not in ORDER:
        raise ValueError("Windows diagnostic inputs required")
    # Construct the same first public S08 envelope. No runtime activation, model
    # discovery, private Instance, network operation or source-dependent grammar.
    cases = json.loads((ROOT / "tests/fixtures/ai_synthesis_quality.json").read_bytes())
    case = next(row for row in cases if row["id"] == "en-summary-facts")
    paragraphs = case["text"].split("\n\n")
    descriptor = native_format("summary-en-v1", len(paragraphs))
    payload = json.dumps({
        "schema_version": 1,
        "trusted": {"template": {"id": "summary-en-v1"},
                    "instructions": instructions(2, "en") + " " + selection_request("en")},
        "untrusted": {"segments": [{"segment": i, "text": text}
                                   for i, text in enumerate(paragraphs)]},
    }, ensure_ascii=False, separators=(",", ":"))
    prompt = native_prompt(payload, descriptor)
    source = (ROOT / "core/provelume/ai_llama.py").read_text(encoding="utf-8")
    if source.count(CONTEXT_LINE) != 1:
        raise ValueError("diagnostic source substitution no longer exact")
    variant = source.replace(CONTEXT_LINE, CONTEXT_LINE.replace("512, 128", f"512, {microbatch}"))
    # Each isolated child compiles exactly one public source variant. These are
    # byte-identified experimental modules, not Git commits or accepted sources.
    module = types.ModuleType("provelume._s08_diagnostic_variant")
    module.__package__ = "provelume"
    exec(compile(variant, "<public-s08-diagnostic-variant>", "exec"), module.__dict__)
    result = {
        "status": "STARTED", "microbatch_tokens": microbatch,
        "source_module_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "variant_module_sha256": hashlib.sha256(variant.encode()).hexdigest(),
        "model_sha256": MODEL_SHA256, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "case": case["id"], "environment": hardware(), "events": [],
        "cold_condition": "fresh process; OS file cache not flushed",
    }
    job, limits = contain()
    result["limits"] = limits
    directory = artifacts / "windows"
    entry = ModelRegistry.packaged().entry(MODEL_ID)
    with ExitStack() as stack:
        model = stack.enter_context(open_local_file(artifacts / "model.gguf"))
        verify_stream(model, entry)
        libraries = {name: directory / name for name in runtime_lock()["platforms"]["windows"]}
        for path in libraries.values():
            stack.enter_context(open_local_file(path))
        LocalRuntime(directory).validate_installation()
        started = time.monotonic()
        engine = module.Llama(directory, artifacts / "model.gguf", libraries)
        stack.callback(engine.close)
        result["load_seconds"] = time.monotonic() - started

        def observe(value):
            result["events"].append({**value, "since_load_start": time.monotonic() - started})

        result["inference"] = engine.generate(payload, observe, scope="0" * 64,
                                              response_format=descriptor)
        result["memory"] = memory_observation()
        result["total_seconds"] = time.monotonic() - started
        result["status"] = "MEASURED"
        if job is False:
            raise ValueError("missing containment lifetime")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", type=int, choices=sorted(set(ORDER)))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output path; existing diagnostic evidence is retained")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.child is not None:
        result = child(args.artifacts.resolve(), args.child)
    else:
        if os.name != "nt":
            parser.error("This diagnostic requires Windows")
        if any(args.output.with_name(f"s08-prefill-{i}.{suffix}").exists()
               for i in range(len(ORDER)) for suffix in ("json", "log")):
            parser.error("Existing child diagnostics must be retained")
        result = {
            "schema": "provelume-s08-prefill-diagnostic/v1", "qualification": "NOT_EVALUATED",
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip(),
            "fixed_order": ORDER, "rows": [], "network_observation": "UNOBSERVED",
            "purpose": "paired microbatch cost observation; not an S08 gate or a retry",
        }
        for index, microbatch in enumerate(ORDER):
            output = args.output.with_name(f"s08-prefill-{index}.json")
            log = args.output.with_name(f"s08-prefill-{index}.log")
            row = {"index": index, "microbatch_tokens": microbatch, "status": "NOT_COMPLETED"}
            command = [sys.executable, str(Path(__file__).resolve()),
                       "--artifacts", str(args.artifacts.resolve()), "--output", str(output),
                       "--child", str(microbatch)]
            with log.open("wb") as stream:
                try:
                    process = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                             stdout=stream, stderr=subprocess.STDOUT,
                                             timeout=90, check=False)
                    row["exit_code"] = process.returncode
                    if output.exists():
                        raw = output.read_bytes()
                        row.update(status="OBSERVED", report=json.loads(raw),
                                   report_sha256=hashlib.sha256(raw).hexdigest())
                except subprocess.TimeoutExpired:
                    row["status"] = "TIMED_OUT"
            result["rows"].append(row)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
