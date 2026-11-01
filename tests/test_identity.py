import os
import time

import pytest

from agentroot import cli, identity
from conftest import sqlite_db

DDL = ["create table remote_control_enrollments (websocket_url text, account_id text, app_server_client_name text, "
       "server_id text, environment_id text, server_name text, updated_at integer, remote_control_enabled integer)"]


def enroll(home, name, folder=".codex"):
    db = home / folder / "state_5.sqlite"
    sqlite_db(db, DDL, [("insert into remote_control_enrollments values (?,?,?,?,?,?,?,?)",
                         [("wss://x", "acct", "Codex Desktop", "srv_old", "env_old", name, 1, 1)])])
    return db


def names(db):
    import sqlite3
    con = sqlite3.connect(db)
    try:
        return [r[0] for r in con.execute("select server_name from remote_control_enrollments")]
    finally:
        con.close()


def test_enrollment_of_this_machine_is_fine(tmp_path):
    enroll(tmp_path / "home", "NEWPC")
    assert identity.check(str(tmp_path / "home"), host="newpc") == []


def test_enrollment_copied_from_another_machine_is_found_and_fixed(tmp_path):
    home = tmp_path / "home"
    db = enroll(home, "OLDPC")
    found = identity.check(str(home), host="NEWPC")
    assert [f.kind for f in found] == ["enrollment"]
    assert '"OLDPC"' in found[0].detail and '"NEWPC"' in found[0].detail
    assert names(db) == ["OLDPC"], "check must not write"

    done = identity.fix(str(home), host="NEWPC")
    assert len(done) == 1 and names(db) == []
    backups = list((home / ".agentroot" / "identity-backup").rglob("*state_5.sqlite"))
    assert backups and names(backups[0]) == ["OLDPC"]
    assert identity.check(str(home), host="NEWPC") == []


def test_fix_keeps_this_machines_enrollment(tmp_path):
    home = tmp_path / "home"
    db = enroll(home, "NEWPC")
    assert identity.fix(str(home), host="NEWPC") == []
    assert names(db) == ["NEWPC"]


def test_database_without_the_table_is_ignored(tmp_path):
    home = tmp_path / "home"
    sqlite_db(home / ".codex" / "state_5.sqlite", ["create table threads (id text)"], [])
    assert identity.check(str(home), host="NEWPC") == []


@pytest.mark.skipif(os.name != "nt", reason="creation time means 'created here' only on Windows")
def test_store_data_copied_from_another_machine_is_found(tmp_path):
    home = tmp_path / "home"
    cache = home / "AppData" / "Local" / "Packages" / "OpenAI.Codex_abc" / "LocalCache" / "Roaming" / "Codex"
    cache.mkdir(parents=True)
    old, new = cache / "Local State", cache / "Preferences"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    month_ago = time.time() - 30 * 86400
    os.utime(old, (month_ago, month_ago))  # what a copy preserves: the old modification time

    found = identity.check(str(home), host="NEWPC")
    assert [f.kind for f in found] == ["store-data"]
    assert "1 of 2 files" in found[0].detail and "Reset-AppxPackage" in found[0].fix


@pytest.mark.skipif(os.name != "nt", reason="creation time means 'created here' only on Windows")
def test_store_data_created_here_is_fine(tmp_path):
    cache = tmp_path / "home" / "AppData" / "Local" / "Packages" / "OpenAI.Codex_abc" / "LocalCache"
    cache.mkdir(parents=True)
    (cache / "Local State").write_text("{}", encoding="utf-8")
    assert identity.check(str(tmp_path / "home"), host="NEWPC") == []


@pytest.mark.skipif(os.name != "nt", reason="creation time means 'created here' only on Windows")
def test_resources_the_app_installs_are_not_mistaken_for_a_copy(tmp_path):
    # a fresh install unpacks extensions and dictionaries with their build dates
    ext = tmp_path / "home" / "AppData" / "Local" / "Packages" / "OpenAI.Codex_abc" / "LocalCache" / "Default" / "Extensions" / "x"
    ext.mkdir(parents=True)
    f = ext / "service_worker.js"
    f.write_text("//", encoding="utf-8")
    os.utime(f, (315532800, 315532800))  # 1980, the zip epoch
    assert identity.check(str(tmp_path / "home"), host="NEWPC") == []


def test_cli_reports_then_fixes(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    db = enroll(home, "OLDPC")
    monkeypatch.setattr(identity, "hostname", lambda: "NEWPC")
    assert cli.main(["identity", "--home", str(home)]) == 3
    assert names(db) == ["OLDPC"]
    assert cli.main(["identity", "--home", str(home), "--fix"]) == 0  # a --home copy is never refused as running
    assert names(db) == []
    assert "removed 1 enrollment" in capsys.readouterr().out
