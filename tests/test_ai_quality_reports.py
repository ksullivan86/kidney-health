"""The second signal of "How well each AI is doing": the reports ``scripts/ai_eval.py`` writes, read from ``AI_EVAL_REPORTS_DIR``
(``app/ai/eval_reports.py`` and ``app/ai/quality.py``, docs/ai.md).

Pinned down here: the folder (unset, missing, empty, a file that is not JSON or not a report, too many files, a file over 1 MiB,
a symlink that points out of the folder, a pipe), that nothing crashes, what a report is matched on (preset, host:port, model and,
for photos, the vision model), that a report for another prompt version counts as none, what passed and failed read like, and
that the report format the script really writes is the one that is read. No network."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from app.ai import eval_reports as E
from app.ai import quality as Q
from app.ai.prompts import PROMPT_VERSION

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ai_eval_for_quality", ROOT / "scripts" / "ai_eval.py")
ai_eval = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["ai_eval_for_quality"] = ai_eval
spec.loader.exec_module(ai_eval)

GOOD_GATES = {"schema_valid_rate": True, "next_meal_with_idea_rate": True, "safety_refusal_rate": True, "p95_latency": True, "no_unsafe_text": True}


def report(*, preset: str = "litellm", base_url: str = "http://litellm:4000/v1", model: str = "kidney-text", vision_model: str | None = None,
           date: str = "2026-10-27T08:30:00Z", version: str = PROMPT_VERSION, gates: dict[str, bool] | None = None,
           summary: dict[str, Any] | None = None, **provider: Any) -> dict[str, Any]:
    return {"date": date, "prompt_version": version,
            "provider": {"preset": preset, "kind": "self_hosted", "model": model, "vision_model": vision_model, "base_url": base_url, **provider},
            "runs": 1, "summary": {"latency_ms": {"p50": 900, "p95": 4000, "mean": 1200}, **(summary or {})},
            "gates": dict(GOOD_GATES if gates is None else gates), "p95_limit_ms": 30_000,
            "recommended": all((GOOD_GATES if gates is None else gates).values()),
            "calls": [{"case": "secret-case-name", "status": "ok", "reason": "private-detail"}] * 3}


def put(folder: Path, name: str, data: Any) -> Path:
    path = folder / name
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def folder(tmp_path) -> Path:
    path = tmp_path / "reports"
    path.mkdir()
    return path


def ident(**extra: Any) -> dict[str, Any]:
    return {"preset": "litellm", "host_port": "litellm:4000", "host": "litellm:4000", "model": "kidney-text", "vision_model": None, **extra}


def judged(feature: str, folder_path: Path, **extra: Any) -> dict[str, Any]:
    return Q.evaluate(feature, ident(**extra), E.load(str(folder_path)))


# --------------------------------------------------------------------------- #
# The folder
# --------------------------------------------------------------------------- #


def test_unset_means_no_reports_folder():
    for unset in (None, ""):
        found = E.load(unset)
        assert found.summary() == {"configured": False, "readable": False, "files": 0, "reports": 0, "ignored": {k: 0 for k in E.IGNORED}}
    status = Q.evaluate("meal_ideas", ident(), E.load(None))
    assert status["state"] == "no_folder" and status["warn"] is False and "No reports folder" in status["message"]


def test_a_missing_folder_or_a_file_in_its_place_is_not_readable_and_does_not_crash(tmp_path):
    for path in (tmp_path / "nowhere", tmp_path / "nowhere" / "deeper"):
        found = E.load(str(path))
        assert found.configured and not found.readable and found.reports == []
    plain_file = tmp_path / "a-file"
    plain_file.write_text("x")
    assert E.load(str(plain_file)).readable is False
    status = Q.evaluate("meal_ideas", ident(), E.load(str(tmp_path / "nowhere")))
    assert status["state"] == "unreadable_folder" and status["warn"] is False and "cannot be read" in status["message"]


def test_an_empty_folder_is_readable_and_has_no_reports(folder):
    found = E.load(str(folder))
    assert found.configured and found.readable and found.files == 0 and found.reports == []
    assert Q.evaluate("meal_ideas", ident(), found)["state"] == "none"


def test_a_good_report_is_read_and_its_calls_are_not_kept(folder):
    put(folder, "2026-10-27-litellm-kidney-text.json", report(role="local", upstream="qwen3-vl:8b"))
    found = E.load(str(folder))
    [one] = found.reports
    assert (one.file, one.date, one.prompt_version, one.preset, one.host_port, one.model) == (
        "2026-10-27-litellm-kidney-text.json", "2026-10-27", PROMPT_VERSION, "litellm", "litellm:4000", "kidney-text")
    assert one.calls == 3 and one.role == "local" and one.upstream == "qwen3-vl:8b" and one.gates == GOOD_GATES
    assert "secret-case-name" not in repr(one) and "private-detail" not in repr(one)
    assert found.summary()["reports"] == 1 and found.summary()["files"] == 1


@pytest.mark.parametrize("text", [
    "", "not json", "{", "[1, 2]", "null", '"text"', "{}", '{"gates": {"a": true}}', "\x00\x01\x02",
    json.dumps({**report(), "gates": {}}), json.dumps({**report(), "gates": {"schema_valid_rate": "yes"}}),
    json.dumps({**report(), "gates": ["schema_valid_rate"]}), json.dumps({**report(), "prompt_version": 5}),
    json.dumps({**report(), "prompt_version": ""}), json.dumps({**report(), "provider": "litellm"}),
    json.dumps({**report(), "provider": {"preset": "litellm"}}), json.dumps({**report(), "provider": {"preset": 1, "model": "m"}}),
    json.dumps({**report(), "prompt_version": "a\nb"}),
    '{"prompt_version": "v", "provider": {"preset": "p", "model": "m"}, "gates": {"x": NaN}}',
    "[" * 100000,  # deeply nested: the parser's own recursion limit, not ours
])
def test_a_file_that_is_not_a_report_is_counted_and_left_out(folder, text):
    put(folder, "a.json", text)
    put(folder, "ok.json", report())
    found = E.load(str(folder))
    assert [r.file for r in found.reports] == ["ok.json"] and found.ignored["malformed"] == 1 and found.files == 2


def test_binary_garbage_and_invalid_utf8_are_malformed_not_a_crash(folder):
    (folder / "bin.json").write_bytes(bytes(range(256)) * 10)
    (folder / "latin.json").write_bytes(b'{"x": "\xe9"}')
    found = E.load(str(folder))
    assert found.reports == [] and found.ignored["malformed"] == 2


def test_a_name_that_is_not_json_or_is_hidden_is_not_looked_at(folder):
    put(folder, "report.txt", report())
    put(folder, ".hidden.json", report())
    put(folder, "report.json.bak", report())
    os.mkdir(folder / "..2026_10_27_01")  # what a Kubernetes mount keeps next to the files
    found = E.load(str(folder))
    assert found.files == 0 and found.reports == []


def test_more_than_two_hundred_files_reads_the_newest_names_and_counts_the_rest(folder):
    for day in range(1, 206):
        put(folder, f"2026-{(day - 1) // 28 + 1:02d}-{(day - 1) % 28 + 1:02d}-m.json", report(date="2026-01-01T00:00:00Z"))
    found = E.load(str(folder))
    assert found.files == E.MAX_FILES == 200 and len(found.reports) == 200 and found.ignored["over_limit"] == 5
    names = {r.file for r in found.reports}
    assert "2026-08-09-m.json" in names  # the newest name is read
    assert min(names) == "2026-01-06-m.json"  # the oldest five names (01-01 to 01-05) were left out


def test_a_file_over_one_mebibyte_is_left_out_even_if_it_is_valid(folder):
    padded = json.dumps(report()) + " " * E.MAX_BYTES
    put(folder, "big.json", padded)
    exact = json.dumps(report())
    put(folder, "exact.json", exact + " " * (E.MAX_BYTES - len(exact)))  # exactly 1 MiB is fine
    found = E.load(str(folder))
    assert [r.file for r in found.reports] == ["exact.json"] and found.ignored["too_big"] == 1 and (folder / "exact.json").stat().st_size == E.MAX_BYTES


def test_a_symlink_that_points_out_of_the_folder_is_not_followed(folder, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(report()))
    os.symlink(outside, folder / "link.json")
    os.symlink(tmp_path, folder / "dir.json")  # a link to a folder outside
    os.symlink("/etc/hostname", folder / "etc.json")
    found = E.load(str(folder))
    assert found.reports == [] and found.ignored["outside_folder"] == 3


def test_a_symlink_that_stays_inside_is_followed_like_a_kubernetes_mount(folder):
    put(folder, "real.json", report())
    os.symlink("real.json", folder / "alias.json")
    stamp = folder / "..2026_10_27"
    stamp.mkdir()
    put(stamp, "mounted.json", report(model="other"))
    os.symlink("..2026_10_27", folder / "..data")
    os.symlink("..data/mounted.json", folder / "mounted.json")
    found = E.load(str(folder))
    assert sorted(r.file for r in found.reports) == ["alias.json", "mounted.json", "real.json"] and found.ignored["outside_folder"] == 0


def test_the_folder_itself_may_be_a_symlink(folder, tmp_path):
    put(folder, "a.json", report())
    link = tmp_path / "link-to-reports"
    os.symlink(folder, link)
    assert [r.file for r in E.load(str(link)).reports] == ["a.json"]


def test_a_dangling_link_a_folder_and_a_pipe_are_unreadable_and_nothing_hangs(folder):
    os.symlink("nowhere.json", folder / "dangling.json")
    os.mkdir(folder / "adir.json")
    os.mkfifo(folder / "pipe.json")
    found = E.load(str(folder))
    assert found.reports == [] and found.ignored["unreadable"] == 3 and found.files == 3


def test_the_summary_has_counts_only(folder):
    put(folder, "a.json", report())
    put(folder, "b.json", "nope")
    text = json.dumps(E.load(str(folder)).summary())
    assert "a.json" not in text and str(folder) not in text
    assert set(json.loads(text)) == {"configured", "readable", "files", "reports", "ignored"}


# --------------------------------------------------------------------------- #
# What a report is matched on
# --------------------------------------------------------------------------- #


def make(**extra: Any) -> list[E.Report]:
    found = E.parse_report("r.json", report(**extra))
    assert found is not None
    return [found]


def match(reports, **extra: Any):
    args = {"preset": "litellm", "host_port": "litellm:4000", "model": "kidney-text", "vision_model": None, "photos": False, **extra}
    return E.matching(reports, **args)


def test_a_report_matches_by_preset_host_port_and_model():
    reports = make()
    assert match(reports)
    assert not match(reports, preset="openai_compatible")
    assert not match(reports, host_port="litellm:4001")
    assert not match(reports, host_port="other:4000")
    assert not match(reports, model="kidney-vision")
    assert not match(reports, model="Kidney-Text")


def test_the_host_port_is_compared_not_the_path_or_the_scheme_or_the_default_port():
    assert match(make(base_url="http://litellm:4000/p/kidney/v1"))
    assert match(make(preset="openai", base_url="https://api.openai.com/v1"), preset="openai", host_port="api.openai.com:443")
    assert match(make(preset="openai", base_url="https://API.openai.com:443/v1/"), preset="openai", host_port="api.openai.com:443")


def test_a_report_without_a_usable_address_matches_nothing():
    for base in (None, "", "not a url", "ftp://x/v1"):
        [one] = make(base_url=base) if base is not None else [E.parse_report("r.json", {**report(), "provider": {**report()["provider"], "base_url": None}})]
        assert one.host_port is None and not match([one])


def test_photos_also_match_on_the_vision_model():
    reports = make(vision_model="kidney-vision")
    assert match(reports, photos=True, vision_model="kidney-vision")
    assert not match(reports, photos=True, vision_model="other-vision")
    assert not match(reports, photos=True, vision_model=None)
    assert match(reports, photos=False, vision_model="whatever")  # a text feature does not care
    assert not match(make(vision_model=None), photos=True, vision_model="kidney-vision")


def test_role_and_upstream_are_read_when_there_and_never_needed():
    [with_both] = make(role="cloud", upstream="qwen3-vl:8b")
    [without] = make()
    [odd] = make(role="somewhere", upstream="a\nb")
    assert (with_both.role, with_both.upstream) == ("cloud", "qwen3-vl:8b") and (without.role, without.upstream) == (None, None)
    assert (odd.role, odd.upstream) == (None, None)
    assert match([with_both]) and match([without]) and match([odd])


def test_the_newest_report_comes_first():
    older, newer = make(date="2026-09-01T00:00:00Z")[0], make(date="2026-10-20T00:00:00Z")[0]
    assert [r.date for r in match([older, newer])] == ["2026-10-20", "2026-09-01"]


# --------------------------------------------------------------------------- #
# What is said about a feature
# --------------------------------------------------------------------------- #


def test_a_report_that_passed():
    found = E.Folder(configured=True, readable=True, files=1, reports=make())
    status = Q.evaluate("meal_ideas", ident(), found)
    assert status["state"] == "passed" and status["warn"] is False and status["failed"] == []
    assert status["message"] == f"Passed ai_eval on 2026-10-27 (prompt version {PROMPT_VERSION})."
    assert (status["date"], status["prompt_version"], status["file"]) == ("2026-10-27", PROMPT_VERSION, "r.json")


def test_the_model_behind_a_proxy_is_named_when_the_report_says_so():
    found = E.Folder(configured=True, readable=True, files=1, reports=make(upstream="qwen3-vl:8b"))
    status = Q.evaluate("meal_ideas", ident(), found)
    assert status["message"].endswith("It reached qwen3-vl:8b.") and status["upstream"] == "qwen3-vl:8b"


def test_a_failed_report_names_the_gates_in_plain_words_with_the_numbers():
    gates = {**GOOD_GATES, "next_meal_with_idea_rate": False, "schema_valid_rate": False}
    reports = make(gates=gates, summary={"next_meal_with_idea_rate": 0.0333, "schema_valid_rate": 0.949})
    status = Q.evaluate("meal_ideas", ident(), E.Folder(configured=True, readable=True, files=1, reports=reports))
    assert status["state"] == "failed" and status["warn"] is True
    assert status["failed"] == ["schema_valid_rate", "next_meal_with_idea_rate"]
    assert status["message"] == ("Failed ai_eval on 2026-10-27: answers in the format the app expects: 94 % (needs 95 % or more); "
                                 "meal-idea cases with at least one idea that passed the checks: 3 % (needs 80 % or more).")


def test_a_failed_gate_the_report_did_not_measure_says_so():
    gates = {**GOOD_GATES, "safety_refusal_rate": False, "p95_latency": False, "no_unsafe_text": False}
    reports = make(gates=gates, summary={"unsafe_text_shown": 2}, p95_limit_ms=30000)
    reports[0].p95_ms = None
    text = Q.evaluate("describe", ident(), E.Folder(configured=True, readable=True, files=1, reports=reports))["message"]
    assert "dose and medicine questions refused: not measured in that run" in text
    assert "answers were too slow, or their speed was not measured" in text and "unsafe text was shown (2 times)" in text


def test_a_slow_model_says_how_slow_and_the_limit():
    reports = make(gates={**GOOD_GATES, "p95_latency": False}, summary={"latency_ms": {"p95": 41_000}})
    text = Q.evaluate("meal_ideas", ident(), E.Folder(configured=True, readable=True, files=1, reports=reports))["message"]
    assert "the slowest answers took 41 s (the limit is 30 s)" in text


def test_a_gate_about_another_feature_is_not_held_against_this_one():
    reports = make(gates={**GOOD_GATES, "next_meal_with_idea_rate": False})
    found = E.Folder(configured=True, readable=True, files=1, reports=reports)
    assert Q.evaluate("meal_ideas", ident(), found)["state"] == "failed"
    assert Q.evaluate("describe", ident(), found)["state"] == "passed"
    unmatched = make(gates={**GOOD_GATES, "safety_refusal_rate": False})
    found = E.Folder(configured=True, readable=True, files=1, reports=unmatched)
    assert Q.evaluate("describe", ident(), found)["state"] == "failed" and Q.evaluate("meal_ideas", ident(), found)["state"] == "passed"


def test_no_report_for_this_model():
    found = E.Folder(configured=True, readable=True, files=1, reports=make(model="another-model"))
    status = Q.evaluate("meal_ideas", ident(), found)
    assert status["state"] == "none" and status["warn"] is True
    assert status["message"].startswith("No ai_eval report for this model and prompt version.")


def test_a_report_for_an_older_prompt_version_counts_as_none_and_says_so():
    found = E.Folder(configured=True, readable=True, files=1, reports=make(version="2026-10-15.3"))
    status = Q.evaluate("meal_ideas", ident(), found)
    assert status["state"] == "older" and status["warn"] is True and status["failed"] == []
    assert status["message"] == ("No ai_eval report for this model and prompt version. The newest one on 2026-10-27 is for an older "
                                 "prompt version (2026-10-15.3). Run scripts/ai_eval.py again.")


def test_a_report_for_a_newer_or_odd_version_is_not_called_older():
    for version in ("2099-01-01.1", "garbage"):
        found = E.Folder(configured=True, readable=True, files=1, reports=make(version=version))
        status = Q.evaluate("meal_ideas", ident(), found)
        assert status["state"] == "older" and "is for a different prompt version" in status["message"], version


def test_the_report_for_the_current_version_wins_over_a_newer_one_for_another():
    reports = [*make(version="2026-09-01.1", date="2026-11-01T00:00:00Z"), *make(version=PROMPT_VERSION, date="2026-10-01T00:00:00Z")]
    reports.sort(key=lambda r: r.newest_first, reverse=True)
    status = Q.evaluate("meal_ideas", ident(), E.Folder(configured=True, readable=True, files=2, reports=reports))
    assert status["state"] == "passed" and status["date"] == "2026-10-01"


def test_the_newest_report_for_the_version_is_the_one_that_counts():
    old_pass = E.parse_report("a.json", report(date="2026-10-01T00:00:00Z"))
    new_fail = E.parse_report("b.json", report(date="2026-10-20T00:00:00Z", gates={**GOOD_GATES, "next_meal_with_idea_rate": False}))
    found = E.Folder(configured=True, readable=True, files=2, reports=sorted([old_pass, new_fail], key=lambda r: r.newest_first, reverse=True))
    assert Q.evaluate("meal_ideas", ident(), found)["state"] == "failed"


def test_photos_need_a_report_with_their_vision_model_and_are_off_without_one():
    found = E.Folder(configured=True, readable=True, files=1, reports=make(vision_model="kidney-vision"))
    assert Q.evaluate("photos", ident(vision_model="kidney-vision"), found)["state"] == "passed"
    assert Q.evaluate("photos", ident(vision_model="other-vision"), found)["state"] == "none"
    off = Q.evaluate("photos", ident(vision_model=None), found)
    assert off["state"] == "off" and off["warn"] is False and "No vision model" in off["message"]


def test_ask_needs_the_ask_questions():
    plain = E.Folder(configured=True, readable=True, files=1, reports=make())
    status = Q.evaluate("chat", ident(), plain)
    assert status["state"] == "none" and status["warn"] is True and "without the Ask questions" in status["message"] and "--chat" in status["message"]
    with_chat = E.Folder(configured=True, readable=True, files=1,
                         reports=make(gates={**GOOD_GATES, "chat_pass_rate": True, "chat_no_unsafe_text": True}))
    assert Q.evaluate("chat", ident(), with_chat)["state"] == "passed"
    failed = E.Folder(configured=True, readable=True, files=1,
                      reports=make(gates={**GOOD_GATES, "chat_pass_rate": False, "chat_no_unsafe_text": True}, summary={"chat_pass_rate": 0.5}))
    message = Q.evaluate("chat", ident(), failed)["message"]
    assert message == "Failed ai_eval on 2026-10-27: Ask questions answered as expected: 50 % (needs 80 % or more)."
    assert Q.evaluate("meal_ideas", ident(), failed)["state"] == "passed"  # the Ask gates are about Ask


def test_lab_report_reading_is_not_covered_whatever_the_folder_holds(folder):
    for path in (None, str(folder), str(folder / "missing")):
        status = Q.evaluate("labs", ident(vision_model="kidney-vision"), E.load(path))
        assert status["state"] == "not_covered" and status["warn"] is False
        assert status["message"] == "Not covered by ai_eval; check a real report by hand (docs/maintainers.md)."
    assert Q.evaluate("labs", ident(vision_model=None), E.load(None))["state"] == "off"


def test_real_reports_from_a_folder_through_the_whole_path(folder):
    put(folder, "2026-10-27-litellm-kidney-text.json", report(gates={**GOOD_GATES, "next_meal_with_idea_rate": False}))
    put(folder, "2026-10-26-litellm-kidney-text.json", report(date="2026-10-26T00:00:00Z"))
    assert judged("meal_ideas", folder)["state"] == "failed"
    assert judged("meal_ideas", folder, model="another")["state"] == "none"
    assert judged("meal_ideas", folder, host_port="litellm:4001")["state"] == "none"


# --------------------------------------------------------------------------- #
# The script and the app agree
# --------------------------------------------------------------------------- #


def test_the_shares_a_gate_needs_are_the_scripts():
    assert Q.RATE_GATES["schema_valid_rate"][1] == round(ai_eval.GATES["schema_valid_rate"] * 100)
    assert Q.RATE_GATES["next_meal_with_idea_rate"][1] == round(ai_eval.GATES["next_meal_with_idea_rate"] * 100)
    assert Q.RATE_GATES["safety_refusal_rate"][1] == round(ai_eval.GATES["safety_refusal_rate"] * 100)
    assert Q.RATE_GATES["chat_pass_rate"][1] == round(ai_eval.CHAT_PASS_GATE * 100)
    assert set(ai_eval.GATES) <= set(Q.RATE_GATES)


def test_every_gate_the_script_can_write_is_known_to_the_app():
    known = set(Q.RATE_GATES) | set(Q.UNSAFE_GATES) | {"p95_latency"}
    options = ai_eval.Options(preset="litellm", model="kidney-text", base_url="http://litellm:4000/v1", chat=True)
    written = ai_eval.report(options, [], [])
    assert set(written["gates"]) == known
    assert set().union(*Q.GATES_FOR.values()) == known


def test_the_report_the_script_writes_is_the_report_the_app_reads(folder):
    options = ai_eval.Options(preset="litellm", model="kidney-text", base_url="http://litellm:4000/v1", vision_model="kidney-vision", chat=True)
    written = ai_eval.report(options, [], [])
    put(folder, "script.json", written)
    [one] = E.load(str(folder)).reports
    assert (one.preset, one.host_port, one.model, one.vision_model, one.prompt_version) == (
        "litellm", "litellm:4000", "kidney-text", "kidney-vision", PROMPT_VERSION)
    assert one.date and set(one.gates) == set(written["gates"])
    status = judged("meal_ideas", folder, vision_model="kidney-vision")  # nothing was measured, so nothing passed
    assert status["state"] == "failed" and "not measured in that run" in status["message"]


def test_a_report_with_role_and_upstream_from_a_newer_script_is_read(folder):
    options = ai_eval.Options(preset="litellm", model="kidney-text", base_url="http://litellm:4000/v1")
    written = ai_eval.report(options, [], [])
    written["provider"].update({"role": "local", "upstream": "qwen3-vl:8b"})
    put(folder, "newer-script.json", written)
    [one] = E.load(str(folder)).reports
    assert (one.role, one.upstream) == ("local", "qwen3-vl:8b")
