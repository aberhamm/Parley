package analyticsrelay

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

type admission struct {
	Schema           int     `json:"schema"`
	Generation       *uint64 `json:"generation"`
	State            string  `json:"state"`
	CheckedAt        string  `json:"checked_at"`
	ValidUntil       string  `json:"valid_until"`
	ContractSchema   int     `json:"contract_schema"`
	PolicySHA256     string  `json:"policy_sha256"`
	WebsiteID        string  `json:"website_id"`
	CollectorVersion string  `json:"collector_version"`
	CollectorImage   string  `json:"collector_image"`
	TrackerSHA256    string  `json:"tracker_sha256"`
	AppBuild         string  `json:"app_build"`
}

func trustedOwner(info os.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && (stat.Uid == 0 || stat.Uid == uint32(os.Geteuid()))
}
func privateFile(info os.FileInfo) bool {
	return trustedOwner(info) && info.Mode().Perm()&0022 == 0
}
func safeDirectory(dir string) bool {
	if !filepath.IsAbs(dir) || filepath.Clean(dir) != dir {
		return false
	}
	// Every ancestor is checked. Sticky system temporary directories are safe
	// ancestors; the state directory itself must be private and never sticky.
	for path := dir; ; path = filepath.Dir(path) {
		info, err := os.Lstat(path)
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return false
		}
		if !privateFile(info) && !(path != dir && trustedOwner(info) && info.Mode()&os.ModeSticky != 0) {
			return false
		}
		if path == filepath.Dir(path) {
			break
		}
	}
	return true
}
func (r *Relay) admitted(ctx context.Context) bool {
	if !safeDirectory(r.cfg.StateDir) {
		return false
	}
	f, err := os.OpenFile(filepath.Join(r.cfg.StateDir, "admission.json"), os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return false
	}
	defer f.Close()
	if r.afterOpen != nil {
		r.afterOpen()
	}
	if ctx.Err() != nil {
		return false
	}
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() || !privateFile(info) || info.Size() > 8192 {
		return false
	}
	b, err := io.ReadAll(io.LimitReader(f, 8193))
	if err != nil || len(b) > 8192 || ctx.Err() != nil {
		return false
	}
	var a admission
	if err = strictJSON(b, &a); err != nil {
		return false
	}
	checked, e1 := utcTime(a.CheckedAt)
	until, e2 := utcTime(a.ValidUntil)
	now := time.Now()
	return e1 == nil && e2 == nil && a.Schema == 1 && a.Generation != nil && a.State == "ready" && a.ContractSchema == policy.Schema && a.PolicySHA256 == PolicySHA256() && a.WebsiteID == policy.Website && a.CollectorVersion == policy.CollectorVersion && a.CollectorImage == policy.CollectorImage && a.TrackerSHA256 == policy.TrackerSHA256 && a.AppBuild == r.cfg.ArtifactSHA256 && checked.Before(now.Add(5*time.Second)) && until.After(now) && until.After(checked) && until.Sub(checked) <= 60*time.Second && now.Sub(checked) <= 60*time.Second && ctx.Err() == nil
}
func utcTime(s string) (time.Time, error) {
	if !strings.HasSuffix(s, "Z") {
		return time.Time{}, errors.New("not UTC")
	}
	return time.Parse(time.RFC3339Nano, s)
}
