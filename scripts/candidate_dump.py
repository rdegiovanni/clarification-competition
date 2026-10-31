"""v7 (`laaser_pinpoint_smt_3.py`) that also records its candidate implementations.

Dev tooling (not part of the submission). Same behaviour as v7 with the same config; in
addition, every time `verify_by_execution` runs several implementations in the sandbox, the
codes and the index `choose_candidate` picked are appended as one JSON line to the file named by
the CANDIDATE_DUMP environment variable. `scripts/candidate_headroom.py` then scores every
candidate with the official tests, to see how often one candidate passes but another is chosen.

Usage:
  CANDIDATE_DUMP=results/candidates/<name>.jsonl PYTHONINTMAXSTRDIGITS=0 scripts/evaluate.sh \
      --clarify-py scripts/candidate_dump.py ...
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import clarify.algorithms.laaser_pinpoint_smt_3 as v7

CURRENT: dict[str, Any] = {}
run_candidates = v7.run_candidates
choose_candidate = v7.choose_candidate


def recording_run_candidates(env, codes, entry_point, calls):
    reports = run_candidates(env, codes, entry_point, calls)
    if len(codes) > 1:
        CURRENT["codes"] = list(codes)
        CURRENT["chosen"] = None
    return reports


def recording_choose_candidate(reports, probes):
    chosen = choose_candidate(reports, probes)
    if "codes" in CURRENT:
        CURRENT["chosen"] = chosen
    return chosen


v7.run_candidates = recording_run_candidates
v7.choose_candidate = recording_choose_candidate


class CandidateDump(v7.LAASeR_PinpointSMT):
    def run(self, env, problem):
        CURRENT.clear()
        code = super().run(env, problem)
        path = os.environ.get("CANDIDATE_DUMP")
        if path and "codes" in CURRENT:
            record = {
                "prompt_sha": hashlib.sha256(problem["prompt"].strip().encode()).hexdigest(),
                "codes": CURRENT["codes"],
                "chosen": CURRENT["chosen"],
                "final": code,
            }
            with open(path, "a") as f:
                f.write(json.dumps(record) + "\n")
        return code
