package db

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// Fork migration rules (homelab plan 248): applied migrations never change,
// upstream migrations are renumbered above the fork's highest number, and every
// file is recorded in deploy/scrum-pro-htz4/MIGRATIONS.lock.

const deployDir = "../../deploy/scrum-pro-htz4"

func sha(b []byte) string {
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

func migNumber(name string) (int, bool) {
	if len(name) < 5 || name[4] != '_' {
		return 0, false
	}
	n, err := strconv.Atoi(name[:4])
	return n, err == nil
}

// tsvRows returns non-empty lines split on tabs, header and comments skipped.
func tsvRows(text string, cols int) ([][]string, []string) {
	var rows [][]string
	var problems []string
	for i, line := range strings.Split(text, "\n") {
		line = strings.TrimRight(line, "\r")
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		f := strings.Split(line, "\t")
		if len(f) != cols {
			problems = append(problems, fmt.Sprintf("line %d: want %d tab-separated fields, got %d", i+1, cols, len(f)))
			continue
		}
		rows = append(rows, f)
	}
	return rows, problems
}

// checkRenumber returns every rule violation for the given migration files
// (name -> content), lock file text and renumbers TSV text.
func checkRenumber(files map[string][]byte, lockText, tsvText string) []string {
	var problems []string

	// Two files sharing a number.
	byNum := map[int][]string{}
	for name := range files {
		n, ok := migNumber(name)
		if !ok {
			problems = append(problems, "bad migration file name: "+name)
			continue
		}
		byNum[n] = append(byNum[n], name)
	}
	for n, names := range byNum {
		if len(names) > 1 {
			sort.Strings(names)
			problems = append(problems, fmt.Sprintf("duplicate number %04d: %s", n, strings.Join(names, ", ")))
		}
	}

	// Lock: every locked file exists with the same hash.
	lockRows, p := tsvRows(lockText, 2)
	problems = append(problems, p...)
	locked := map[string]string{}
	lockMax := 0
	for _, r := range lockRows {
		if _, dup := locked[r[0]]; dup {
			problems = append(problems, "lock lists twice: "+r[0])
		}
		locked[r[0]] = r[1]
		if n, ok := migNumber(r[0]); ok && n > lockMax {
			lockMax = n
		}
		c, ok := files[r[0]]
		if !ok {
			problems = append(problems, "locked file missing: "+r[0])
		} else if sha(c) != r[1] {
			problems = append(problems, "locked file changed: "+r[0])
		}
	}

	// Unlocked files must sit above the lock's highest number.
	for name := range files {
		if _, ok := locked[name]; ok {
			continue
		}
		n, ok := migNumber(name)
		if ok && n <= lockMax {
			problems = append(problems, fmt.Sprintf("unlocked file %s is numbered at or below the lock's highest (%04d)", name, lockMax))
		}
	}

	// Renumbers TSV: upstream_file, fork_file, sync_commit, sha256_of_upstream_content.
	// The first row is the header.
	tsvAll, p := tsvRows(tsvText, 4)
	problems = append(problems, p...)
	if len(tsvAll) > 0 {
		seen := map[string]bool{}
		for _, r := range tsvAll[1:] {
			if seen[r[0]] {
				problems = append(problems, "upstream name appears twice in TSV: "+r[0])
			}
			seen[r[0]] = true
			c, ok := files[r[1]]
			if !ok {
				problems = append(problems, "renamed file missing: "+r[1])
			} else if sha(c) != r[3] {
				problems = append(problems, fmt.Sprintf("TSV hash mismatch for %s (fork file %s)", r[0], r[1]))
			}
		}
	}
	sort.Strings(problems)
	return problems
}

func readInputs(t *testing.T) (map[string][]byte, string, string) {
	t.Helper()
	files := map[string][]byte{}
	entries, err := fs.ReadDir(MigrationsFS, "migrations")
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		b, err := fs.ReadFile(MigrationsFS, "migrations/"+e.Name())
		if err != nil {
			t.Fatal(err)
		}
		files[e.Name()] = b
	}
	lock, err := os.ReadFile(filepath.Join(deployDir, "MIGRATIONS.lock"))
	if err != nil {
		t.Fatal(err)
	}
	tsv, err := os.ReadFile(filepath.Join(deployDir, "MIGRATION-RENUMBERS.tsv"))
	if err != nil {
		t.Fatal(err)
	}
	return files, string(lock), string(tsv)
}

func TestRenumberRulesHold(t *testing.T) {
	files, lock, tsv := readInputs(t)
	if got := checkRenumber(files, lock, tsv); len(got) > 0 {
		t.Fatalf("migration rules violated:\n%s", strings.Join(got, "\n"))
	}
}

func cloneFiles(m map[string][]byte) map[string][]byte {
	c := make(map[string][]byte, len(m))
	for k, v := range m {
		c[k] = v
	}
	return c
}

func wantProblem(t *testing.T, got []string, substr string) {
	t.Helper()
	for _, g := range got {
		if strings.Contains(g, substr) {
			return
		}
	}
	t.Fatalf("want a problem containing %q, got %v", substr, got)
}

func TestRenumberNegativeDuplicateNumber(t *testing.T) {
	files, lock, tsv := readInputs(t)
	f := cloneFiles(files)
	f["0063_other_thing.sql"] = []byte("select 1;")
	wantProblem(t, checkRenumber(f, lock, tsv), "duplicate number 0063")
}

func TestRenumberNegativeEditedLockedFile(t *testing.T) {
	files, lock, tsv := readInputs(t)
	f := cloneFiles(files)
	f["0001_extensions.sql"] = append(append([]byte{}, f["0001_extensions.sql"]...), []byte("\n-- edit\n")...)
	wantProblem(t, checkRenumber(f, lock, tsv), "locked file changed: 0001_extensions.sql")
}

func TestRenumberNegativeUnlockedLowNumberedFile(t *testing.T) {
	files, lock, tsv := readInputs(t)
	f := cloneFiles(files)
	f["0031_slipped_in.sql"] = []byte("select 1;") // below lock max, not in lock
	got := checkRenumber(f, lock, tsv)
	wantProblem(t, got, "unlocked file 0031_slipped_in.sql")
}

func TestRenumberNegativeTSVHashMismatch(t *testing.T) {
	files, lock, tsv := readInputs(t)
	// A rename recorded with the wrong upstream hash.
	row := "0060_upstream_thing.sql\t0063_guest_profile_erasure.sql\tdeadbeef\t" + strings.Repeat("0", 64) + "\n"
	got := checkRenumber(files, lock, tsv+row)
	wantProblem(t, got, "TSV hash mismatch")
	// The same upstream name twice is also rejected.
	good := "0060_upstream_thing.sql\t0063_guest_profile_erasure.sql\tdeadbeef\t" + sha(files["0063_guest_profile_erasure.sql"]) + "\n"
	wantProblem(t, checkRenumber(files, lock, tsv+good+good), "appears twice")
}
