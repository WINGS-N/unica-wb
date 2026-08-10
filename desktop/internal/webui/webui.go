// Package webui carries the build interface inside the launcher binary, so a
// packaged desktop app needs no separate web server
package webui

import (
	"embed"
	"io"
	"io/fs"
	"net/http"
	"path"
	"strings"
)

// The tree is produced by the frontend build and is empty in a plain checkout,
// which is why every accessor tolerates a missing index
//
//go:embed all:dist
var embedded embed.FS

var content fs.FS

func init() {
	sub, err := fs.Sub(embedded, "dist")
	if err != nil {
		return
	}
	content = sub
}

// Available reports whether a real build was embedded
func Available() bool {
	if content == nil {
		return false
	}
	f, err := content.Open("index.html")
	if err != nil {
		return false
	}
	_ = f.Close()
	return true
}

// Handler serves the single page app: real files as they are, every other path
// as index.html so the router owns the address bar
func Handler() http.Handler {
	files := http.FileServer(http.FS(content))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !Available() {
			http.Error(w, "interface not embedded", http.StatusNotFound)
			return
		}
		name := strings.TrimPrefix(path.Clean(r.URL.Path), "/")
		if name == "" || name == "." {
			serveIndex(w, r)
			return
		}
		if _, err := fs.Stat(content, name); err != nil {
			serveIndex(w, r)
			return
		}
		// A fresh port on every launch would otherwise reuse a stale worker
		if name == "sw.js" {
			w.Header().Set("Cache-Control", "no-cache")
		}
		files.ServeHTTP(w, r)
	})
}

func serveIndex(w http.ResponseWriter, r *http.Request) {
	f, err := content.Open("index.html")
	if err != nil {
		http.Error(w, "interface not embedded", http.StatusNotFound)
		return
	}
	defer f.Close()
	body, err := io.ReadAll(f)
	if err != nil {
		http.Error(w, "cannot read the interface", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	if r.Method == http.MethodHead {
		w.WriteHeader(http.StatusOK)
		return
	}
	_, _ = w.Write(body)
}
