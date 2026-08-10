//go:build !linux || !cgo

package gtkwin

import "unsafe"

// MakeTransparent is a no-op where the window toolkit already honours an
// alpha background
func MakeTransparent(handle unsafe.Pointer) {}
