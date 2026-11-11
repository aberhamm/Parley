package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
)

func optionalAnalyticsConfig(upstream, state string) (string, string) {
	// This is a fixed private deployment seam, never an operator-supplied proxy.
	if upstream != "http://scrum-analytics-collector:3000" || !filepath.IsAbs(state) || filepath.Clean(state) != state {
		return "", ""
	}
	return upstream, state
}
func runningExecutableSHA256() (string, error) {
	// Production Linux opens the loaded executable inode even if its path was
	// renamed. A non-Linux process has no asserted immutable-runtime custody.
	if runtime.GOOS != "linux" {
		return "", errors.New("analytics executable custody unsupported")
	}
	return hashExecutable(func() (io.ReadCloser, error) {
		f, err := os.Open("/proc/self/exe")
		if err != nil {
			return nil, err
		}
		info, err := f.Stat()
		if err != nil || !info.Mode().IsRegular() {
			f.Close()
			return nil, errors.New("invalid running executable")
		}
		return f, nil
	})
}
func hashExecutable(open func() (io.ReadCloser, error)) (string, error) {
	f, err := open()
	if err != nil {
		return "", fmt.Errorf("opening executable: %w", err)
	}
	defer f.Close()
	hash := sha256.New()
	n, err := io.Copy(hash, io.LimitReader(f, 256*1024*1024+1))
	if err != nil {
		return "", fmt.Errorf("hashing executable: %w", err)
	}
	if n == 0 || n > 256*1024*1024 {
		return "", errors.New("invalid executable size")
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}
