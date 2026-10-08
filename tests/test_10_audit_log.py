"""Audit log: every call is persisted, failures included, and logging never raises."""
import config
from common import audit


def _use_tmp_audit_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DB_PATH", tmp_path / "audit_log.db")


def test_record_call_persists_success(tmp_path, monkeypatch):
    _use_tmp_audit_db(tmp_path, monkeypatch)
    response = {
        "final_response": "Your credit is pending approval.",
        "execution_trace": [{"worker": "BillingResolutionADK", "output": "x"}, {"worker": "CustomerCommsCrew", "output": "y"}],
        "agent_context": "ctx",
    }
    audit_id = audit.record_call("CUST-10002 charged twice", response, duration_ms=1234)
    assert audit_id

    record = audit.get_call(audit_id)
    assert record["status"] == "SUCCESS"
    assert record["workers_called"] == "BillingResolutionADK > CustomerCommsCrew"
    assert record["step_count"] == 2
    assert record["duration_ms"] == 1234
    assert record["execution_trace"][0]["worker"] == "BillingResolutionADK"
    assert record["final_response"] == "Your credit is pending approval."


def test_record_call_persists_errors(tmp_path, monkeypatch):
    _use_tmp_audit_db(tmp_path, monkeypatch)
    audit_id = audit.record_call("q", {"error": "boom", "execution_trace": []}, duration_ms=5)
    record = audit.get_call(audit_id)
    assert record["status"] == "ERROR"
    assert record["error_message"] == "boom"


def test_list_calls_newest_first_and_empty_when_no_db(tmp_path, monkeypatch):
    _use_tmp_audit_db(tmp_path, monkeypatch)
    assert audit.list_calls() == []
    first = audit.record_call("first", {"execution_trace": []}, 1)
    second = audit.record_call("second", {"execution_trace": []}, 1)
    assert [c["audit_id"] for c in audit.list_calls()] == [second, first]


def test_record_call_never_raises(tmp_path, monkeypatch):
    # Point the audit DB at a path that cannot be opened (a directory).
    monkeypatch.setattr(config, "AUDIT_DB_PATH", tmp_path)
    assert audit.record_call("q", {"execution_trace": []}, 1) is None


def test_audit_db_survives_init_db_rebuild():
    # The audit log is a separate file from the business DB that init_db.py rebuilds.
    assert config.AUDIT_DB_PATH != config.DB_PATH
