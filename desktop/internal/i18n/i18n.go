package i18n

import (
	_ "embed"
	"encoding/json"
)

// The web UI pushes its own strings over the bridge; these are what the
// launcher shows before that happens
//
//go:embed strings.json
var raw []byte

// Progress text is produced in English deep inside the startup sequence, so it
// is translated by lookup rather than by key
type pack struct {
	UI       map[string]string `json:"ui"`
	Messages map[string]string `json:"messages"`
}

var catalog map[string]pack

func init() {
	_ = json.Unmarshal(raw, &catalog)
}

// Get returns an interface string for a language, falling back to English
func Get(language, key string) string {
	if value, ok := catalog[language].UI[key]; ok && value != "" {
		return value
	}
	return catalog["en"].UI[key]
}

// UI is the whole interface catalog for a language, English filling the gaps
func UI(language string) map[string]string {
	return merged(catalog["en"].UI, catalog[language].UI)
}

// Messages maps the English progress text to a language
func Messages(language string) map[string]string {
	return merged(catalog["en"].Messages, catalog[language].Messages)
}

func merged(base, over map[string]string) map[string]string {
	out := make(map[string]string, len(base)+len(over))
	for k, v := range base {
		out[k] = v
	}
	for k, v := range over {
		if v != "" {
			out[k] = v
		}
	}
	return out
}
