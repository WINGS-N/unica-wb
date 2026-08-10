//go:build linux && cgo

// Package gtkwin reaches past the window toolkit for the few things it does not
// expose. On GTK4 a window keeps painting the theme background underneath a
// transparent webview, which puts a light frame around a rounded page
package gtkwin

/*
#cgo pkg-config: gtk4
#cgo CFLAGS: -Wno-deprecated-declarations
#include <gtk/gtk.h>

static const char *unica_css =
	"window.unica-transparent,"
	"window.unica-transparent > *,"
	"window.unica-transparent decoration {"
	"  background-color: transparent;"
	"  background-image: none;"
	"  box-shadow: none;"
	"  border: none;"
	"}";

static void unica_make_transparent(void *handle) {
	GtkWidget *widget = GTK_WIDGET(handle);
	if (widget == NULL) {
		return;
	}
	gtk_widget_add_css_class(widget, "unica-transparent");

	GtkCssProvider *provider = gtk_css_provider_new();
	gtk_css_provider_load_from_data(provider, unica_css, -1);
	gtk_style_context_add_provider_for_display(
		gtk_widget_get_display(widget),
		GTK_STYLE_PROVIDER(provider),
		GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
	g_object_unref(provider);
}
*/
import "C"

import "unsafe"

// MakeTransparent stops the window from painting anything of its own, so the
// page decides the shape. The handle is the toolkit window pointer
func MakeTransparent(handle unsafe.Pointer) {
	if handle == nil {
		return
	}
	C.unica_make_transparent(handle)
}
