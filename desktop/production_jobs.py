"""Small, conservative local Comfy graph runner; no model or service lifecycle logic.

Spec: graph, inputs [{node, field, path}], dependencies [path], environment {identity},
output {node, key, type: output, extension: .png}, optional retry_errors [exception_type].
Declare all file-backed inputs, including custom loader files, as bindings/dependencies.
LoadImage/LoadAudio are checked automatically; arbitrary custom-node ambient reads are
outside this contract. Environment identity is caller supplied, never inferred from names.
Technical completion and recorded review do not establish semantic/media quality.
"""

import argparse
from contextlib import contextmanager
import copy
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path, PureWindowsPath
import shutil
import tempfile
import time
from urllib import error, parse, request
import uuid


VERSION = "1"


def canonical(value):
    def validate(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("JSON object keys must be strings")
            for child in item.values():
                validate(child)
        elif isinstance(item, list):
            for child in item:
                validate(child)
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError("Only JSON values are supported")
    validate(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(root):
    """OS releases the lock on process exit; retained lock files are harmless."""
    path = Path(root) / ".lock"
    with path.open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Revision is locked by another runner") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def confined(root, relative):
    p = Path(relative)
    windows = PureWindowsPath(str(relative))
    if p.is_absolute() or windows.is_absolute() or windows.drive or ".." in windows.parts or ".." in p.parts:
        raise ValueError("Unsafe relative media path")
    target = (Path(root) / p).resolve()
    if not target.is_relative_to(Path(root).resolve()):
        raise ValueError("Media path escapes its root")
    return target


def checked_bytes(path, expected=None):
    data = Path(path).read_bytes()
    if not data or (expected is not None and digest(data) != expected):
        raise ValueError("Missing, empty or changed artifact: " + str(path))
    return data


def file_hash(path, expected=None):
    path = Path(path)
    with path.open("rb") as stream:
        value = hashlib.file_digest(stream, "sha256").hexdigest()
    if not path.stat().st_size or (expected is not None and value != expected):
        raise ValueError("Empty or changed artifact: " + str(path))
    return value


def immutable_bytes(path, data):
    """Exclusive create, then verify; never overwrite a content-addressed artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        pass
    checked_bytes(path, digest(data))


def implementation_hash():
    return digest(Path(__file__).read_bytes())


def prepare(spec, project_root, engine_input, engine_output):
    spec = copy.deepcopy(spec)
    canonical(spec)
    graph = spec["graph"]
    if not isinstance(graph, dict) or not graph or any(not isinstance(k, str) for k in graph):
        raise ValueError("Expected API graph with string node IDs")
    if not isinstance(spec.get("environment"), dict) or not spec["environment"]:
        raise ValueError("Explicit environment identity required (unknown values must be recorded)")
    selector = spec["output"]
    if selector.get("node") not in graph or selector.get("type") != "output":
        raise ValueError("Output must select a graph node and output storage")
    extension = selector.get("extension", "")
    if not extension.startswith(".") or not extension[1:].isalnum() or not selector.get("key"):
        raise ValueError("Output collection and single media extension required")
    saver = graph[selector["node"]].get("inputs", {})
    if not isinstance(saver.get("filename_prefix"), str):
        raise ValueError("Selected saver must expose a literal filename_prefix")
    auxiliaries = spec.get('auxiliary', [])
    if not isinstance(auxiliaries, list) or len(auxiliaries) > 1 or len({a.get('node') for a in auxiliaries}) != len(auxiliaries):
        raise ValueError('Auxiliary selectors must be unique')
    for auxiliary in auxiliaries:
        if (auxiliary.get('node') not in graph or auxiliary['node'] == selector['node']
                or auxiliary.get('kind') != 'h3-av-safetensors-v1'
                or auxiliary.get('key') != 'studio_av' or auxiliary.get('extension') != '.safetensors'
                or auxiliary.get('type') != 'output'):
            raise ValueError('Unsupported auxiliary selector')
    project_root = Path(project_root).resolve()
    engine_input = Path(engine_input).resolve()
    engine_output = Path(engine_output).resolve()
    records, bindings = [], set()
    for binding in spec.get("inputs", []):
        node, field = binding["node"], binding["field"]
        if (node, field) in bindings or node not in graph or field not in graph[node].get("inputs", {}):
            raise ValueError("Invalid or duplicate input binding")
        bindings.add((node, field))
        source = Path(binding["path"]).resolve(strict=True)
        data = checked_bytes(source)
        name = "production-inputs/" + digest(data) + source.suffix.lower()
        immutable_bytes(confined(engine_input, name), data)
        graph[node]["inputs"][field] = name
        records.append({"path": str(source), "sha256": digest(data), "staged": name, "node": node, "field": field})
    for node, value in graph.items():
        if value.get("class_type", "").startswith("Save") and not isinstance(value.get("inputs", {}).get("filename_prefix"), str):
            raise ValueError("Saver nodes require explicit literal filename_prefix: " + node)
        for field in {"LoadImage": ("image",), "LoadAudio": ("audio",), "LoadVideo": ("file",), "LoadStudioAV": ("file",)}.get(value.get("class_type"), ()):
            if (node, field) not in bindings:
                raise ValueError("Undeclared file loader: " + node + "." + field)
    for source in spec.get("dependencies", []):
        source = Path(source).resolve(strict=True)
        records.append({"path": str(source), "sha256": file_hash(source)})
    payload = {"version": VERSION, "implementation_sha256": implementation_hash(), "spec": spec,
               "sources": records, "project_root": str(project_root), "engine_input": str(engine_input),
               "engine_output": str(engine_output)}
    revision_id = digest(canonical(payload))
    root = project_root / "revisions" / revision_id
    root.mkdir(parents=True, exist_ok=True)
    with locked(root):
        record = {"revision": revision_id, **payload}
        target = root / "revision.json"
        if target.exists():
            if read_json(target) != record:
                raise ValueError("Revision record corruption")
        else:
            atomic_json(target, record)
    return root


def load_revision(root):
    root = Path(root).resolve()
    record = read_json(root / "revision.json")
    payload = {k: v for k, v in record.items() if k != "revision"}
    if digest(canonical(payload)) != record["revision"] or root.name != record["revision"]:
        raise ValueError("Revision fingerprint mismatch")
    return record


def source_issues(record):
    issues = []
    if record["implementation_sha256"] != implementation_hash():
        issues.append("runner implementation changed")
    for source in record["sources"]:
        try:
            file_hash(source["path"], source["sha256"])
        except (OSError, ValueError):
            issues.append("source changed: " + source["path"])
        if "staged" in source:
            file_hash(confined(record["engine_input"], source["staged"]), source["sha256"])
    return issues


def validate_result(root, result, record, attempt):
    if (result.get("revision") != record["revision"] or result.get("prompt_id") != attempt["id"]
            or result.get("graph_sha256") != attempt["graph_sha256"] or len(result.get("outputs", [])) != 1):
        raise ValueError("Invalid completed result identity or cardinality")
    item = result["outputs"][0]
    extension = record["spec"]["output"]["extension"].lower()
    expected_copy = "results/" + attempt["id"] + extension
    target = Path(item["path"]).resolve()
    prefix = confined(record["engine_output"], attempt["output_prefix"])
    if (item["copy"] != expected_copy or target.parent != prefix.parent
            or not target.name.startswith(prefix.name) or target.suffix.lower() != extension):
        raise ValueError("Completed result path differs from selected attempt")
    file_hash(confined(root, item["copy"]), item["sha256"])
    file_hash(target, item["sha256"])
    if target.stat().st_size != item["bytes"]:
        raise ValueError("Completed result size changed")
    declared = record['spec'].get('auxiliary', [])
    companions = result.get('auxiliary', [])
    if len(declared) != len(companions):
        raise ValueError('Missing or undeclared auxiliary artifacts')
    for selector, companion in zip(declared, companions):
        if selector.get('kind') != 'h3-av-safetensors-v1' or companion.get('kind') != selector['kind']:
            raise ValueError('Unsupported auxiliary artifact type')
        expected = confined(record['engine_output'], attempt['output_prefix'] + '-' + selector['node'])
        path = Path(companion['path']).resolve()
        if path.parent != expected.parent or not path.name.startswith(expected.name) or path.suffix != '.safetensors':
            raise ValueError('Auxiliary artifact is not owned by the completed attempt')
        relative = 'results/' + attempt['id'] + '-' + selector['node'] + '.safetensors'
        if companion['copy'] != relative:
            raise ValueError('Auxiliary copy identity mismatch')
        file_hash(path, companion['sha256'])
        file_hash(confined(root, relative), companion['sha256'])


def status(root, criteria=None):
    record = load_revision(root)
    issues = source_issues(record)
    state = read_json(Path(root) / "state.json") if (Path(root) / "state.json").exists() else {"status": "prepared", "attempts": []}
    approved = False
    if state.get("result"):
        validate_result(root, state["result"], record, state["attempts"][-1])
        path = Path(root) / "review.json"
        if path.exists():
            review_record = read_json(path)
            approved = (review_record["accepted"] and review_record["revision"] == record["revision"]
                        and review_record["result_sha256"] == digest(canonical(state["result"]))
                        and (criteria is None or review_record["criteria"] == criteria))
    return {**state, "current": not issues, "source_issues": issues, "approved": bool(approved and not issues)}


def review(root, criteria, evidence, accepted=True):
    with locked(root):
        current = status(root)
        if current["status"] != "completed" or not current["current"]:
            raise ValueError("Only a current, validated completed result can be reviewed")
        if not criteria or not evidence:
            raise ValueError("Review needs criteria version and evidence; it does not perform semantic checks")
        result = {"revision": load_revision(root)["revision"], "result_sha256": digest(canonical(current["result"])),
                  "accepted": bool(accepted), "criteria": criteria, "evidence": evidence,
                  "note": "Caller-recorded review; runner performed no semantic evaluation."}
        immutable_bytes(Path(root) / ("review-" + digest(canonical(result)) + ".json"), canonical(result))
        atomic_json(Path(root) / "review.json", result)
        return result


def endpoint_url(endpoint):
    parsed = parse.urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Expected plain HTTP loopback engine origin")
    try:
        local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = False
    if not local:
        raise ValueError("Engine endpoint must be loopback")
    return endpoint.rstrip("/")


def http_json(endpoint, method, route, payload=None):
    data = canonical(payload) if payload is not None else None
    req = request.Request(endpoint + route, data=data, method=method, headers={"Content-Type": "application/json"})
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("Engine redirects are not allowed")

    with request.build_opener(NoRedirect).open(req, timeout=10) as response:
        return json.load(response)


def selected_result(root, record, attempt, history):
    selector = record["spec"]["output"]
    candidates = history.get("outputs", {}).get(selector["node"], {}).get(selector["key"], [])
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError("Selected output must contain exactly one candidate")
    media = candidates[0]
    if media.get("type") != selector["type"] or Path(media.get("filename", "")).suffix.lower() != selector["extension"].lower():
        raise ValueError("Selected output has wrong storage type or extension")
    # Validate components separately: an absolute filename must not be hidden by joining.
    confined(record["engine_output"], media["filename"])
    subfolder = confined(record["engine_output"], media.get("subfolder", ""))
    target = confined(subfolder, media["filename"])
    expected = confined(record["engine_output"], attempt["output_prefix"])
    if target.parent != expected.parent or not target.name.startswith(expected.name):
        raise ValueError("Output is not in this attempt's isolated saver prefix")
    relative = "results/" + attempt["id"] + selector["extension"].lower()
    destination = confined(root, relative)
    destination.parent.mkdir(exist_ok=True)
    source_hash = file_hash(target)
    try:
        with target.open("rb") as source, destination.open("xb") as sink:
            shutil.copyfileobj(source, sink)
            sink.flush()
            os.fsync(sink.fileno())
    except FileExistsError:
        pass
    file_hash(destination, source_hash)
    file_hash(target, source_hash)
    result = {"revision": record["revision"], "prompt_id": attempt["id"],
            "graph_sha256": attempt["graph_sha256"],
            "outputs": [{"path": str(target), "copy": relative, "sha256": source_hash, "bytes": target.stat().st_size}]}
    companions = []
    for auxiliary in record['spec'].get('auxiliary', []):
        selector_record = copy.deepcopy(record)
        selector_record['spec']['output'] = auxiliary
        selector_record['spec']['auxiliary'] = []
        owned = {**attempt, 'output_prefix': attempt['output_prefix'] + '-' + auxiliary['node']}
        collected = selected_result(root, selector_record, owned, history)['outputs'][0]
        proper = 'results/' + attempt['id'] + '-' + auxiliary['node'] + '.safetensors'
        original_copy = confined(root, collected['copy'])
        destination = confined(root, proper)
        # One AV companion per attempt; preserve exactly one primary media output.
        immutable_bytes(destination, checked_bytes(original_copy, collected['sha256']))
        companions.append({**collected, 'copy': proper, 'kind': auxiliary['kind']})
    if companions:
        result['auxiliary'] = companions
    return result


def numeric_graph(value):
    """Comfy validation casts integer literals for FLOAT inputs, without changing values."""
    if isinstance(value, dict):
        return {key: numeric_graph(item) for key, item in value.items()}
    if isinstance(value, list):
        return [numeric_graph(item) for item in value]
    return int(value) if type(value) is float and value.is_integer() else value


def matching_prompt(prompt, attempt):
    expected = attempt['payload']['prompt']
    return (isinstance(prompt, list) and len(prompt) >= 4 and prompt[1] == attempt["id"]
            and digest(canonical(expected)) == attempt["graph_sha256"]
            and canonical(numeric_graph(prompt[2])) == canonical(numeric_graph(expected))
            and prompt[3].get("production_revision") == attempt["revision"])


def run(root, endpoint="http://127.0.0.1:8193", timeout=30, poll_interval=1, max_attempts=2, transport=None,
        reconcile_only=False):
    root = Path(root)
    endpoint = endpoint_url(endpoint)
    if not math.isfinite(timeout) or not math.isfinite(poll_interval) or timeout < 0 or poll_interval < 0 or not 1 <= max_attempts <= 5:
        raise ValueError("Invalid timeout, poll interval or attempt budget (1–5)")
    transport = transport or http_json
    with locked(root):
        record = load_revision(root)
        path = root / "state.json"
        state = read_json(path) if path.exists() else {"status": "prepared", "attempts": [], "max_attempts": max_attempts, "endpoint": endpoint}
        if reconcile_only and not state['attempts']:
            raise ValueError('Read-only reconciliation requires an existing durable attempt')
        issues = [] if reconcile_only else source_issues(record)
        if issues and not state["attempts"]:
            raise ValueError("Revision is stale; prepare a new revision")
        state["current"] = None if reconcile_only else not issues
        state['source_verification'] = 'not repeated during reconciliation' if reconcile_only else 'strong'
        state["source_issues"] = issues
        if state["max_attempts"] != max_attempts or state["endpoint"] != endpoint:
            raise ValueError("Persisted attempt budget/engine cannot change on resume")
        if state["status"] == "completed":
            validate_result(root, state["result"], record, state["attempts"][-1])
            if state.pop("last_poll_error", None) is not None:
                atomic_json(path, state)
            return state
        deadline = time.monotonic() + timeout
        while True:
            last = state["attempts"][-1] if state["attempts"] else None
            if last is None or (not reconcile_only and not issues and state["status"] == "failed" and last.get("retryable") and len(state["attempts"]) < state["max_attempts"]):
                # Recheck immutable staged files immediately before submission.
                if source_issues(record):
                    raise ValueError("Source changed before submission")
                graph = copy.deepcopy(record["spec"]["graph"])
                job_id = str(uuid.uuid4())
                prefix = "production-jobs/" + record["revision"] + "/" + job_id + "/result"
                for node, value in graph.items():
                    if "filename_prefix" in value.get("inputs", {}):
                        value["inputs"]["filename_prefix"] = prefix if node == record["spec"]["output"]["node"] else prefix + "-" + node
                last = {"id": job_id, "revision": record["revision"], "status": "submitting", "output_prefix": prefix,
                        "graph_sha256": digest(canonical(graph)), "payload": {"prompt": graph, "prompt_id": job_id,
                        "extra_data": {"production_revision": record["revision"]}}}
                state["attempts"].append(last)
                state["status"] = "unknown_submission"
                atomic_json(path, state)
                try:
                    reply = transport(endpoint, "POST", "/prompt", last["payload"])
                    if reply.get("prompt_id") != job_id:
                        raise ValueError("Backend did not acknowledge durable UUID")
                    last["status"] = state["status"] = "pending"
                except error.HTTPError as exc:
                    last["error"] = str(exc)
                    if exc.code in (400, 401, 403, 404, 422):
                        last["status"] = state["status"] = "rejected"
                except Exception as exc:
                    last["error"] = str(exc)
                atomic_json(path, state)
            if state["status"] in ("rejected", "invalid_output", "cancelled") or (state["status"] == "failed" and (issues or not last.get("retryable") or len(state["attempts"]) >= state["max_attempts"])):
                return state
            try:
                response = transport(endpoint, "GET", "/history/" + last["id"])
                history = response.get(last["id"])
                if history:
                    if not matching_prompt(history.get("prompt"), last):
                        raise ValueError("History identity mismatch")
                    atomic_json(root / (last["id"] + ".history.json"), history)
                    engine_status = history.get("status", {})
                    if engine_status.get("completed") and engine_status.get("status_str") == "success":
                        try:
                            state["result"] = selected_result(root, record, last, history)
                            state["status"] = last["status"] = "completed"
                            state.pop("last_poll_error", None)
                        except (OSError, ValueError, KeyError, TypeError) as exc:
                            state["status"] = last["status"] = "invalid_output"
                            last["error"] = str(exc)
                        atomic_json(path, state)
                        return state
                    messages = engine_status.get("messages", [])
                    failures = [value for kind, value in messages if kind == "execution_error"]
                    if engine_status.get("status_str") == "error":
                        interrupted = any(kind == 'execution_interrupted' for kind, _ in messages)
                        state["status"] = last["status"] = "cancelled" if interrupted and not failures else "failed"
                        last["retryable"] = bool(failures and failures[-1].get("exception_type") in record["spec"].get("retry_errors", []))
                        last["error"] = messages
                        atomic_json(path, state)
                        continue
                else:
                    queue = transport(endpoint, "GET", "/queue")
                    matches = [p for key in ("queue_running", "queue_pending") for p in queue.get(key, []) if len(p) > 1 and p[1] == last["id"]]
                    if matches and (len(matches) != 1 or not matching_prompt(matches[0], last)):
                        raise ValueError("Queue identity mismatch")
                    if matches:
                        state["status"] = last["status"] = "pending"
                    else:
                        state["status"] = "unknown_submission" if last["status"] == "submitting" else "lost"
            except Exception as exc:
                state["last_poll_error"] = str(exc)
            atomic_json(path, state)
            if time.monotonic() >= deadline:
                return state
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("spec")
    for name in ("project_root", "engine_input", "engine_output"):
        p.add_argument("--" + name.replace("_", "-"), required=True)
    p = sub.add_parser("run")
    p.add_argument("revision")
    p.add_argument("--endpoint", default="http://127.0.0.1:8193")
    p.add_argument("--timeout", type=float, default=30)
    p.add_argument("--max-attempts", type=int, default=2)
    p = sub.add_parser("status")
    p.add_argument("revision")
    p.add_argument("--criteria")
    p = sub.add_parser("review")
    p.add_argument("revision")
    p.add_argument("--criteria", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--reject", action="store_true")
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "prepare":
        source = Path(args["spec"]).resolve(strict=True)
        args["spec"] = read_json(source)
        args["spec"].setdefault("dependencies", []).append(str(source))
        result = str(prepare(**args))
    elif command == "review":
        args["root"] = args.pop("revision")
        args["accepted"] = not args.pop("reject")
        result = review(**args)
    else:
        args["root"] = args.pop("revision")
        result = {"run": run, "status": status}[command](**args)
    print(json.dumps(result, indent=2))
    if command in ("run", "status"):
        if result["status"] in ("pending", "unknown_submission"):
            raise SystemExit(2)
        if result["status"] not in ("completed", "prepared") or result.get("current") is False:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
