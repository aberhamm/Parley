#!/usr/bin/env python3
"""Explicit local-container restore drill; creates/drops only its scratch DB.

Run with --container scrum-invitations-db-20261025. Never accepts a remote DSN.
All contents are synthetic. Requires the local Docker CLI, not a host psql.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("privacy_maintenance", ROOT / "scripts/privacy-maintenance.py")
privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(privacy)
DB = "scrum_privacy_recovery_test"


def ident(number):
    return str(uuid.UUID(int=number))


class ContainerSQL:
    def __init__(self, container): self.container = container

    def run(self, command, data=None):
        result = subprocess.run(["docker", "exec", "-i", self.container, *command], input=data, capture_output=True)
        if result.returncode:
            raise ValueError("local scratch database operation failed")
        return result.stdout

    def query(self, sql):
        output = self.run(["psql", "-U", "parley", "-d", DB, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"], sql.encode()).decode().strip()
        return json.loads(output) if output.startswith("{") else None

    def scalar(self, sql):
        return self.query("select json_build_object('value',(" + sql + "));")["value"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True, choices=["scrum-invitations-db-20261025"])
    args = parser.parse_args()
    client = ContainerSQL(args.container)
    created = False
    result = {}
    try:
        client.run(["createdb", "-U", "parley", DB]); created = True
        for migration in sorted((ROOT / "internal/db/migrations").glob("*.sql")):
            client.query("begin;\n" + migration.read_text() + "\ncommit;")
        owner, other, target, unrelated, guest = [ident(i) for i in range(1001, 1006)]
        keep, erase, foreign, handoff = [ident(i) for i in range(2001, 2005)]
        meeting, cascade, untouched, handoff_meeting = [ident(i) for i in range(3001, 3005)]
        story, other_story, guest_link = [ident(i) for i in range(4001, 4004)]
        org = "00000000-0000-0000-0000-000000000001"
        client.query(f"""
          insert into users(id,name) values ('{owner}','Synthetic owner'),('{other}','Synthetic co-owner'),
              ('{target}','Synthetic profile erase target'),('{unrelated}','Synthetic unrelated owner'),('{guest}','Synthetic guest');
          insert into org_members(org_id,user_id,role) values ('{org}','{owner}','admin'),('{org}','{other}','admin'),
              ('{org}','{target}','member'),('{org}','{unrelated}','member');
          insert into spaces(id,slug,name,creator_id) values ('{keep}','keep','Kept workspace','{owner}'),
              ('{erase}','erase','Erased workspace','{owner}'),('{foreign}','unrelated','Unrelated workspace','{unrelated}'),
              ('{handoff}','handoff','Handoff workspace','{target}');
          insert into members(space_id,user_id,role) values ('{keep}','{owner}','owner'),('{keep}','{target}','member'),
              ('{erase}','{owner}','owner'),('{foreign}','{unrelated}','owner'),('{handoff}','{target}','owner');
          insert into sessions(id,space_id,kind,title,facilitator_id) values ('{meeting}','{keep}','poker','Erase session','{owner}'),
              ('{cascade}','{erase}','standup','Cascaded session','{owner}'),('{untouched}','{foreign}','poker','Untouched session','{unrelated}'),
              ('{handoff_meeting}','{handoff}','standup','Profile contribution','{target}');
          insert into stories(id,session_id,title,position) values ('{story}','{meeting}','Synthetic private story',1),
              ('{other_story}','{untouched}','Unrelated story',1);
          insert into votes(story_id,user_id,value) values ('{story}','{target}','5'),('{story}','{guest}','8'),
              ('{other_story}','{target}','3'),('{other_story}','{unrelated}','5');
          insert into standup_entries(session_id,user_id,today,position) values ('{handoff_meeting}','{target}','Synthetic personal contribution',1);
          insert into session_tokens(token_hash,user_id) values (decode(repeat('ab',32),'hex'),'{target}'),(decode(repeat('cd',32),'hex'),'{guest}');
          insert into hosting_grants(org_id,user_id) values ('{org}','{target}');
          insert into session_links(id,session_id,created_by,token_hash,expires_at) values
              ('{guest_link}','{meeting}','{owner}',decode(repeat('ef',32),'hex'),clock_timestamp()+interval '1 day');
          update users set link_id='{guest_link}' where id='{guest}';
        """)
        untouched_hash = client.scalar(f"select md5(row_to_json(s)::text) from spaces s where id='{foreign}'")
        # This real custom-format backup predates the handoff and every erasure.
        backup = client.run(["pg_dump", "-U", "parley", "-d", DB, "-Fc"])
        assert backup.startswith(b"PGDMP")
        result["custom_format_backup"] = "pass"
        client.query(f"insert into members(space_id,user_id,role) values('{handoff}','{other}','owner');")
        client.query(f"select privacy_erase_profile('{target}'::uuid); select privacy_erase_session('{meeting}'::uuid); select privacy_erase_space('{erase}'::uuid);")
        assert client.scalar(f"select name='Deleted participant' and erased_at is not null from users where id='{target}'")
        assert client.scalar(f"select count(*)=0 from votes where user_id='{target}'")
        assert client.scalar(f"select count(*)=0 from standup_entries where user_id='{target}'")
        assert client.scalar(f"select count(*)=0 from session_tokens where user_id in ('{target}','{guest}')")
        assert client.scalar(f"select erased_at is not null from users where id='{guest}'")
        result["source_erasure_and_link_guest_cleanup"] = "pass"
        with tempfile.TemporaryDirectory(prefix="privacy-recovery-") as tmp:
            path = Path(tmp) / "deletions.json"
            # Exercise the actual CLI/SQLClient. A private psql transport shim
            # uses the container's installed psql because the Studio has none.
            shim = Path(tmp) / "psql"
            shim.write_text("#!/bin/sh\nexec docker exec -i -e PGDATABASE -e PGUSER -e PGCONNECT_TIMEOUT "
                            + args.container + ' psql "$@"\n')
            shim.chmod(0o700)
            cli_env = dict(os.environ, PATH=tmp + os.pathsep + os.environ.get("PATH", ""),
                           DATABASE_URL="postgresql://parley@/" + DB + "?sslmode=disable")
            def cli(*arguments):
                completed = subprocess.run([sys.executable, str(ROOT / "scripts/privacy-maintenance.py"),
                                            *arguments], env=cli_env, text=True, capture_output=True)
                assert completed.returncode == 0, "privacy maintenance CLI failed"
                return json.loads(completed.stdout)
            cli("export", "--journal", str(path))
            data = privacy.read_journal(path)
            assert {r["kind"] for r in data["deletions"]} == {"session", "space", "profile"}
            assert any(r["object_id"] == guest and r["kind"] == "profile" for r in data["deletions"])
            assert client.scalar(f"select md5(row_to_json(s)::text) from spaces s where id='{foreign}'") == untouched_hash
            result["off_backup_minimal_export"] = "pass"
            # Remove the schema and restore the genuine older custom archive.
            client.query("drop schema public cascade; create schema public;")
            client.run(["pg_restore", "-U", "parley", "-d", DB, "--exit-on-error", "--no-owner"], backup)
            assert client.scalar(f"select count(*)=1 from sessions where id='{meeting}'")
            assert client.scalar(f"select count(*)=1 from spaces where id='{erase}'")
            assert client.scalar(f"select erased_at is null from users where id='{target}'")
            result["old_backup_really_restored_deleted_data"] = "pass"
            wrong = dict(data, instance_id=ident(9999))
            try: privacy.replay_journal(wrong, client, writers_stopped=True)
            except ValueError: pass
            else: raise AssertionError("wrong-instance replay was accepted")
            assert client.scalar("select count(*) from privacy_deletions") == 0
            result["wrong_instance_no_effects"] = "pass"
            # The profile is a sole owner in this backup. All earlier deletes in
            # this replay must roll back, not merely the last profile statement.
            try: privacy.replay_journal(data, client, writers_stopped=True)
            except ValueError: pass
            else: raise AssertionError("last-owner restore was exposed")
            assert client.scalar(f"select count(*)=1 from sessions where id='{meeting}'")
            assert client.scalar(f"select count(*)=1 from spaces where id='{erase}'")
            assert client.scalar("select count(*) from privacy_deletions") == 0
            result["last_owner_refusal_rolls_back_every_replayed_deletion"] = "pass"
            client.query(f"insert into members(space_id,user_id,role) values('{handoff}','{other}','owner');")
            replayed = cli("replay", "--journal", str(path), "--writers-stopped")["replayed_receipts"]
            assert replayed == len(data["deletions"])
            assert client.scalar(f"select count(*)=0 from sessions where id in ('{meeting}','{cascade}')")
            assert client.scalar(f"select count(*)=0 from spaces where id='{erase}'")
            assert client.scalar(f"select name='Deleted participant' and erased_at is not null from users where id='{target}'")
            assert client.scalar(f"select count(*)=0 from votes where user_id='{target}'")
            assert client.scalar(f"select count(*)=0 from standup_entries where user_id='{target}'")
            assert client.scalar(f"select count(*)=0 from session_tokens where user_id in ('{target}','{guest}')")
            assert client.scalar(f"select md5(row_to_json(s)::text) from spaces s where id='{foreign}'") == untouched_hash
            assert client.scalar(f"select count(*)=1 from sessions where id='{untouched}'")
            assert client.scalar(f"select count(*)=1 from votes where story_id='{other_story}' and user_id='{unrelated}'")
            result["replay_erases_session_space_profile_and_preserves_unrelated_data"] = "pass"
            privacy.replay_journal(data, client, writers_stopped=True)
            privacy.export_journal(path, client)
            assert len(privacy.read_journal(path)["deletions"]) == len(data["deletions"])
            result["replay_and_export_idempotence"] = "pass"
            result["actual_cli_export_and_replay"] = "pass"
    finally:
        if created:
            client.run(["dropdb", "-U", "parley", DB])
            result["scratch_database_removed"] = DB
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
