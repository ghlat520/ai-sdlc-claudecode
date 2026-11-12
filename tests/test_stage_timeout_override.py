"""Run-time limits must not silently truncate a healthy, longer model task."""

from pathlib import Path

from tests.test_pipeline_contract import executor_case  # noqa: F401


def test_operator_can_disable_timeout_without_changing_dag_or_bypassing_checks(executor_case):
    dag, dag_path, env, run = executor_case
    dag["stages"]["first"]["timeout_seconds"] = 1
    cli = Path(env["PATH"].split(":")[0]) / "claude"
    cli.write_text(cli.read_text().replace(
        "stage = re.search(",
        "import time\ntime.sleep(1.5)\nstage = re.search(",
    ))

    stopped, failed = run("--stages", "S8")
    assert stopped.returncode != 0
    assert failed["stages"]["S8"]["status"] == "dead_letter"
    assert "Stage timed out after 1s" in stopped.stdout
    original_policy = dag_path.read_bytes()

    env["PIPELINE_STAGE_TIMEOUT_SECONDS"] = "0"
    resumed, passed = run("--resume", "--stages", "S8")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert "timeout: unlimited" in resumed.stdout
    assert dag_path.read_bytes() == original_policy
    record = passed["stages"]["S8"]
    assert record["status"] == "passed"
    assert record["verification"]["status"] == "verified"
    assert {check["check"] for check in record["verification"]["evidence"]} == {
        "schema", "post_commands", "gate"
    }
