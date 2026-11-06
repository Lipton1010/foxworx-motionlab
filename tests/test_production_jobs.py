import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError


MODULE = Path(__file__).resolve().parents[1] / "desktop" / "production_jobs.py"
spec = importlib.util.spec_from_file_location("production_jobs", MODULE)
jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jobs)


class FakeEngine:
    def __init__(self, output):
        self.output = output
        self.posts = []
        self.history = {}
        self.queue = []
        self.mode = "complete"
        self.failures = 0
        self.media = None

    def __call__(self, endpoint, method, route, payload=None):
        if method == "POST":
            self.posts.append(copy.deepcopy(payload))
            if self.mode == "reject":
                raise HTTPError(endpoint, 400, "bad graph", {}, None)
            if self.mode == "unknown":
                raise TimeoutError("lost request")
            job_id = payload["prompt_id"]
            prompt = [0, job_id, payload["prompt"], payload["extra_data"], []]
            if self.mode == "pending":
                self.queue.append(prompt)
            else:
                prefix = payload["prompt"]["2"]["inputs"]["filename_prefix"]
                target = self.output / (prefix + "_00001_.png")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"fake completed media")
                media = {"filename": target.name, "subfolder": str(target.parent.relative_to(self.output)), "type": "output"}
                status = {"completed": True, "status_str": "success", "messages": []}
                if self.failures:
                    self.failures -= 1
                    status = {"completed": False, "status_str": "error", "messages": [["execution_error", {"exception_type": "TransientTestError"}]]}
                self.history[job_id] = {"prompt": prompt, "status": status,
                    "outputs": {"2": {"images": self.media if self.media is not None else [media]}, "3": {"images": [media, media]}}}
            if self.mode == "response_loss":
                raise TimeoutError("accepted but response lost")
            return {"prompt_id": job_id}
        if route == "/queue":
            return {"queue_running": self.queue, "queue_pending": []}
        job_id = route.rsplit("/", 1)[1]
        return {job_id: self.history[job_id]} if job_id in self.history else {}


class ProductionJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.input = self.base / "input"
        self.output = self.base / "output"
        self.source = self.base / "source.png"
        self.source.write_bytes(b"source image")
        self.spec = {"graph": {
            "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "do-not-overwrite"}},
            "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "preview"}}},
            "inputs": [{"node": "1", "field": "image", "path": str(self.source)}],
            "dependencies": [], "environment": {"backend": "fake version", "models": "none"},
            "output": {"node": "2", "key": "images", "type": "output", "extension": ".png"},
            "retry_errors": ["TransientTestError"]}
        self.engine = FakeEngine(self.output)

    def prepare(self):
        return jobs.prepare(self.spec, self.base / "project", self.input, self.output)

    def run_job(self, root, **kwargs):
        return jobs.run(root, timeout=0, transport=self.engine, **kwargs)

    def test_success_cache_review_and_explicit_selection(self):
        root = self.prepare()
        result = self.run_job(root)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["result"]["outputs"]), 1)
        self.assertEqual(len(self.engine.posts), 1)
        self.run_job(root)
        self.assertEqual(len(self.engine.posts), 1)
        self.assertFalse(jobs.status(root)["approved"])
        jobs.review(root, "technical-v1", "fake engine fixtures, no semantic checks")
        self.assertTrue(jobs.status(root, "technical-v1")["approved"])
        self.assertFalse(jobs.status(root, "other-criteria")["approved"])
        self.assertNotEqual(self.engine.posts[0]["prompt"]["3"]["inputs"]["filename_prefix"], "preview")

    def test_changed_graph_input_and_dependency_new_revision_preserves_accepted(self):
        root = self.prepare()
        self.run_job(root)
        jobs.review(root, "v1", "fixture accepted")
        old_result = jobs.read_json(root / "state.json")
        self.source.write_bytes(b"changed data")
        self.assertFalse(jobs.status(root)["current"])
        self.assertFalse(jobs.status(root)["approved"])
        self.assertTrue((root / "review.json").exists())
        self.assertFalse(self.run_job(root)["current"])
        second = self.prepare()
        self.assertNotEqual(root, second)
        self.spec["graph"]["2"]["inputs"]["prompt"] = "changed"
        third = self.prepare()
        self.assertNotEqual(second, third)
        dependency = self.base / "intent.json"
        dependency.write_text("approved")
        self.spec["dependencies"] = [str(dependency)]
        fourth = self.prepare()
        dependency.write_text("changed")
        self.assertFalse(jobs.status(fourth)["current"])
        self.assertEqual(jobs.read_json(root / "state.json"), old_result)

    def test_reordered_json_and_same_basename_isolation(self):
        root = self.prepare()
        self.spec = dict(reversed(list(self.spec.items())))
        self.assertEqual(root, self.prepare())
        other = self.base / "other" / self.source.name
        other.parent.mkdir()
        other.write_bytes(b"different image")
        self.spec["graph"]["4"] = {"class_type": "LoadImage", "inputs": {"image": "old.png"}}
        self.spec["inputs"].append({"node": "4", "field": "image", "path": str(other)})
        record = jobs.load_revision(self.prepare())
        self.assertNotEqual(record["sources"][0]["staged"], record["sources"][1]["staged"])

    def test_staged_corruption_and_output_change_fail_closed(self):
        root = self.prepare()
        record = jobs.load_revision(root)
        staged = self.input / record["sources"][0]["staged"]
        staged.write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            self.run_job(root)
        with self.assertRaises(ValueError):
            self.prepare()
        staged.write_bytes(self.source.read_bytes())
        result = self.run_job(root)
        Path(result["result"]["outputs"][0]["path"]).write_bytes(b"replaced")
        with self.assertRaises(ValueError):
            jobs.review(root, "v1", "cannot approve changed output")
        with self.assertRaises(ValueError):
            self.run_job(root)

    def test_response_loss_reconciles_without_repost(self):
        root = self.prepare()
        self.engine.mode = "response_loss"
        self.assertEqual(self.run_job(root)["status"], "completed")
        self.run_job(root)
        self.assertEqual(len(self.engine.posts), 1)

    def test_engine_float_coercion_reconciles_but_changed_values_do_not(self):
        self.spec['graph']['1']['inputs']['strength'] = 1
        for returned, accepted in [(1.0, True), (True, False), ('1', False), (1.01, False)]:
            with self.subTest(returned=returned):
                self.spec['graph']['1']['inputs']['case'] = repr(returned)
                root = self.prepare()
                def coercing_engine(endpoint, method, route, payload=None):
                    reply = self.engine(endpoint, method, route, copy.deepcopy(payload))
                    if method == 'POST':
                        prompt = self.engine.history[payload['prompt_id']]['prompt']
                        prompt[2]['1']['inputs']['strength'] = returned
                    return reply
                state = jobs.run(root, timeout=0, transport=coercing_engine)
                self.assertEqual(state['status'] == 'completed', accepted)
                before = len(self.engine.posts)
                jobs.run(root, timeout=0, transport=coercing_engine)
                self.assertEqual(len(self.engine.posts), before)

    def test_transient_poll_error_pending_identity_and_corrupt_state(self):
        root = self.prepare()
        self.engine.mode = "pending"
        self.run_job(root)
        def unavailable(*args):
            raise ConnectionError("engine temporarily absent")
        state = jobs.run(root, timeout=0, transport=unavailable)
        self.assertEqual(state["status"], "pending")
        self.assertIn("temporarily absent", state["last_poll_error"])
        self.assertEqual(self.run_job(root)["status"], "pending")
        self.engine.queue[0][2]["1"]["inputs"]["image"] = "wrong.png"
        state = self.run_job(root)
        self.assertIn("identity mismatch", state["last_poll_error"])
        self.assertNotEqual(state["status"], "completed")
        (root / "state.json").write_text("{")
        with self.assertRaises(ValueError):
            self.run_job(root)
        self.assertEqual(len(self.engine.posts), 1)

    def test_success_status_required_and_result_copy_corruption(self):
        root = self.prepare()
        self.engine.mode = "response_loss"
        def unfinished(endpoint, method, route, payload=None):
            try:
                return self.engine(endpoint, method, route, payload)
            except TimeoutError:
                self.engine.history[payload["prompt_id"]]["status"]["completed"] = False
                raise
        state = jobs.run(root, timeout=0, transport=unfinished)
        self.assertNotEqual(state["status"], "completed")
        self.engine.history[state["attempts"][0]["id"]]["status"]["completed"] = True
        state = self.run_job(root)
        self.assertEqual(state["status"], "completed")
        (root / state["result"]["outputs"][0]["copy"]).write_bytes(b"changed copy")
        with self.assertRaises(ValueError):
            jobs.status(root)

    def test_pending_resume_and_lost_job_never_resubmits(self):
        root = self.prepare()
        self.engine.mode = "pending"
        pending = self.run_job(root)
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(self.run_job(root)["attempts"][0]["id"], pending["attempts"][0]["id"])
        self.engine.queue.clear()
        self.assertEqual(self.run_job(root)["status"], "lost")
        self.assertEqual(len(self.engine.posts), 1)

    def test_changed_source_pending_reconciles_without_post_or_approval(self):
        root = self.prepare()
        self.engine.mode = "pending"
        state = self.run_job(root)
        prompt = self.engine.queue[0]
        job_id = prompt[1]
        prefix = prompt[2]["2"]["inputs"]["filename_prefix"]
        target = self.output / (prefix + "_00001_.png")
        target.parent.mkdir(parents=True)
        target.write_bytes(b"accepted job final bytes")
        self.engine.history[job_id] = {"prompt": prompt,
            "status": {"completed": True, "status_str": "success", "messages": []},
            "outputs": {"2": {"images": [{"filename": target.name, "subfolder": str(target.parent.relative_to(self.output)), "type": "output"}]}}}
        self.source.write_bytes(b"new creative revision")
        resumed = self.run_job(root)
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["attempts"][0]["id"], state["attempts"][0]["id"])
        self.assertFalse(jobs.status(root)["current"])
        self.assertFalse(jobs.status(root)["approved"])
        self.assertEqual(len(self.engine.posts), 1)
        with self.assertRaises(ValueError):
            jobs.review(root, "v1", "stale must not be accepted as current")

    def test_declared_shared_dependency_invalidates_only_descendants(self):
        selection = self.base / "selected-intent.json"
        selection.write_text('{"approved_take": "v1"}')
        descendants = []
        for stage in ("motion", "assembly"):
            self.spec["graph"]["2"]["inputs"]["stage_label"] = stage
            self.spec["dependencies"] = [str(selection)]
            root = self.prepare()
            self.run_job(root)
            jobs.review(root, "technical-v1", "accepted original " + stage)
            descendants.append((root, (root / "review.json").read_bytes(), (root / "state.json").read_bytes()))
        self.spec["graph"]["2"]["inputs"]["stage_label"] = "unrelated-reference"
        self.spec["dependencies"] = []
        unrelated = self.prepare()
        self.run_job(unrelated)
        jobs.review(unrelated, "technical-v1", "accepted unrelated")
        selection.write_text('{"approved_take": "v2"}')
        for root, review_bytes, state_bytes in descendants:
            with self.subTest(revision=root.name):
                current = jobs.status(root)
                self.assertFalse(current["current"])
                self.assertFalse(current["approved"])
                self.assertTrue(current["result"]["outputs"])
                self.assertEqual((root / "review.json").read_bytes(), review_bytes)
                self.assertEqual((root / "state.json").read_bytes(), state_bytes)
                output = current["result"]["outputs"][0]
                self.assertEqual(jobs.file_hash(root / output["copy"]), output["sha256"])
        self.assertTrue(jobs.status(unrelated)["current"])
        self.assertTrue(jobs.status(unrelated)["approved"])
        self.assertEqual(len(self.engine.posts), 3)

    def test_unknown_submission_and_prepost_crash_never_replay(self):
        root = self.prepare()
        self.engine.mode = "unknown"
        self.assertEqual(self.run_job(root)["status"], "unknown_submission")
        self.run_job(root)
        self.assertEqual(len(self.engine.posts), 1)
        # Durable submitting record is the same conservative state after a crash before POST.
        self.engine.posts.clear()
        self.run_job(root)
        self.assertEqual(self.engine.posts, [])

    def test_bounded_retry_and_persisted_budget(self):
        root = self.prepare()
        self.engine.failures = 2
        result = self.run_job(root)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.engine.posts), 2)
        self.run_job(root)
        self.assertEqual(len(self.engine.posts), 2)
        with self.assertRaises(ValueError):
            self.run_job(root, max_attempts=3)

    def test_rejection_no_retry_and_nonretryable_execution_error(self):
        root = self.prepare()
        self.engine.mode = "reject"
        self.assertEqual(self.run_job(root)["status"], "rejected")
        self.run_job(root)
        self.assertEqual(len(self.engine.posts), 1)
        self.spec["retry_errors"] = []
        self.engine.mode = "complete"
        self.engine.failures = 1
        self.assertEqual(self.run_job(self.prepare())["status"], "failed")
        self.assertEqual(len(self.engine.posts), 2)

    def test_invalid_output_cardinality_type_extension_path_and_empty(self):
        bad = [[], [{"filename": "../escape.png", "type": "output"}],
            [{"filename": "C:\\escape.png", "type": "output"}],
            [{"filename": "x.png", "type": "temp"}],
            [{"filename": "x.mp4", "type": "output"}]]
        for index, media in enumerate(bad):
            with self.subTest(media=media):
                self.spec["graph"]["2"]["inputs"]["case"] = index
                self.engine.media = media
                self.assertEqual(self.run_job(self.prepare())["status"], "invalid_output")
        self.engine.media = None
        self.spec["graph"]["2"]["inputs"]["case"] = "empty"
        def empty(endpoint, method, route, payload=None):
            result = self.engine(endpoint, method, route, payload)
            if method == "POST":
                history = self.engine.history[payload["prompt_id"]]
                media = history["outputs"]["2"]["images"][0]
                (self.output / media["subfolder"] / media["filename"]).write_bytes(b"")
            return result
        self.assertEqual(jobs.run(self.prepare(), timeout=0, transport=empty)["status"], "invalid_output")

    def test_validation_loader_selector_endpoint_and_lock(self):
        root = self.prepare()
        with jobs.locked(root):
            with self.assertRaises(RuntimeError):
                self.run_job(root)
        for endpoint in ("https://127.0.0.1", "http://example.com", "http://127.0.0.1/path", "http://user@localhost"):
            with self.assertRaises(ValueError):
                jobs.run(root, endpoint=endpoint, timeout=0, transport=self.engine)
        self.spec["inputs"] = []
        with self.assertRaises(ValueError):
            self.prepare()

    def test_invalid_json_values_and_unisolated_saver(self):
        with self.assertRaises(ValueError):
            jobs.canonical({1: "not a string key"})
        with self.assertRaises(ValueError):
            jobs.canonical({"number": float("nan")})
        del self.spec["graph"]["3"]["inputs"]["filename_prefix"]
        with self.assertRaises(ValueError):
            self.prepare()

    def test_polling_deadlines_must_be_finite(self):
        root = self.prepare()
        for value in (float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                jobs.run(root, timeout=value, transport=self.engine)
            with self.assertRaises(ValueError):
                jobs.run(root, poll_interval=value, transport=self.engine)
        self.assertEqual(self.engine.posts, [])
        self.spec["output"]["node"] = "unknown"
        with self.assertRaises(ValueError):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
