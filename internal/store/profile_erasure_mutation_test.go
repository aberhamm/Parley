package store

import (
	"context"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
)

// These guards live in migrated SQL, so mutating a migration source file after
// testPool has migrated would change nothing. Replace the actual test-database
// function temporarily and run the same public behavioral assertion in a child
// test process. The child must fail for that assertion, not a setup/build error.
func TestProfileErasureDatabaseGuardMutations(t *testing.T) {
	pool := testPool(t)
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	const lateWrites = "TestProfileErasureRejectsLateWritesAndCannotBeRevived"
	const handoff = "TestProfileErasureRefusesLastOwnerAndAdmin"
	const personal = "TestProfileErasureRemovesPersonalDataAndPreservesSharedMeeting"
	cases := []struct{ name, function, find, replace, test, failure string }{
		{"late token issuance", "privacy_guard_erased_user()", "if found and erased is not null then", "if false then", lateWrites, "late write accepted"},
		{"profile resurrection", "privacy_guard_profile_update()", "if old.erased_at is not null then", "if false then", lateWrites, "late write accepted"},
		{"last workspace owner", "privacy_erase_profile(uuid,uuid)", "own.user_id=target and own.role='owner'", "own.user_id=target and own.role='owner' and false", handoff, "sole owner:"},
		{"last organization admin", "privacy_erase_profile(uuid,uuid)", "own.role='admin' and own.revoked_at is null", "own.role='admin' and own.revoked_at is null and false", handoff, "sole admin:"},
		{"personal vote erasure", "privacy_erase_profile(uuid,uuid)", "delete from votes where user_id=target;", "null;", personal, "votes: count=1"},
		{"durable deletion receipt", "privacy_erase_profile(uuid,uuid)", "insert into privacy_deletions(kind,object_id,deleted_at) values('profile',target,clock_timestamp())\n    on conflict(kind,object_id) do nothing;", "null;", personal, "missing atomic receipt"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var original string
			if err := pool.QueryRow(t.Context(), "select pg_get_functiondef($1::regprocedure)", tc.function).Scan(&original); err != nil {
				t.Fatal(err)
			}
			if strings.Count(original, tc.find) != 1 {
				t.Fatalf("mutation anchor changed for %s", tc.function)
			}
			if _, err := pool.Exec(t.Context(), strings.Replace(original, tc.find, tc.replace, 1)); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() {
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				if _, err := pool.Exec(ctx, original); err != nil {
					t.Errorf("restoring test-database function: %v", err)
				}
			})
			cmd := exec.Command(executable, "-test.run=^"+tc.test+"$", "-test.count=1", "-test.timeout=20s")
			out, err := cmd.CombinedOutput()
			if err == nil {
				t.Fatal("guard mutation survived its behavioral test")
			}
			if !strings.Contains(string(out), tc.failure) {
				t.Fatalf("mutation failed for a setup reason instead of its behavioral assertion: %s", out)
			}
		})
	}
}
