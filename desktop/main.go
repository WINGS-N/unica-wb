package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"sync"
	"sync/atomic"
	"time"

	"github.com/wailsapp/wails/v3/pkg/application"
	"github.com/wailsapp/wails/v3/pkg/events"

	"unica-wb/desktop/internal/bridge"
	"unica-wb/desktop/internal/config"
	"unica-wb/desktop/internal/gtkwin"
	"unica-wb/desktop/internal/i18n"
	"unica-wb/desktop/internal/orch"
	"unica-wb/desktop/internal/webui"
)

const (
	splashWindowName = "splash"
	mainWindowName   = "main"
)

// version is stamped at build time
var version = "dev"

type launcher struct {
	cfg    config.Config
	app    *application.App
	server *bridge.Server
	orch   *orch.Orchestrator

	splash *application.WebviewWindow
	main   *application.WebviewWindow

	quitApproved atomic.Bool
	shuttingDown atomic.Bool
	dialogOpen   atomic.Bool

	i18nMu   sync.RWMutex
	language string
	i18n     map[string]string
}

func main() {
	cfg := config.Load()

	l := &launcher{
		cfg:      cfg,
		language: cfg.Language,
		i18n:     map[string]string{},
	}

	emitter := orch.NewEmitter(func(kind string, payload any) {
		if l.server == nil {
			return
		}
		// "error" is reserved by EventSource for transport failures
		if kind == "error" {
			kind = "error-event"
		}
		l.server.Publish(kind, payload)
	})

	l.server = bridge.New(emitter)
	l.orch = orch.New(cfg, emitter, l.server.AskSudo)

	if cfg.EmbeddedUI {
		if err := l.server.ProxyAPI(cfg.APIURL); err != nil {
			log.Fatalf("cannot route the interface to the api: %v", err)
		}
		if !webui.Available() {
			log.Print("no interface was embedded, falling back to the frontend container")
			cfg.EmbeddedUI = false
			l.cfg = cfg
		}
	}

	l.publishTexts(cfg.Language)

	if _, err := l.server.Start(); err != nil {
		log.Fatalf("cannot start the local bridge: %v", err)
	}

	l.server.OnRetry = func() { l.runStartup() }
	l.server.OnFix = func(kind string) { l.runFix(kind) }
	l.server.OnLanguage = l.setLanguage

	l.app = application.New(application.Options{
		Name:        "UN1CA Build",
		Description: "UN1CA firmware build launcher " + version,
		SingleInstance: &application.SingleInstanceOptions{
			UniqueID: "org.unica.wb.launcher",
			OnSecondInstanceLaunch: func(application.SecondInstanceData) {
				l.focusForeground()
			},
		},
		OnShutdown: func() {
			l.orch.StopKeepalive()
			l.server.Close()
		},
	})

	l.splash = l.newSplashWindow(l.server.SplashURL())

	go l.runStartup()

	if err := l.app.Run(); err != nil {
		log.Fatalf("application stopped: %v", err)
	}
}

func (l *launcher) newSplashWindow(baseURL string) *application.WebviewWindow {
	win := l.app.Window.NewWithOptions(application.WebviewWindowOptions{
		Name:          splashWindowName,
		Title:         "UN1CA Build",
		Width:         780,
		Height:        560,
		DisableResize: true,
		Frameless:     true,
		URL:           baseURL,
		// Transparent so the rounded card is the visible shape of the window
		BackgroundType:   application.BackgroundTypeTransparent,
		BackgroundColour: application.NewRGBA(0, 0, 0, 0),
		InitialPosition:  application.WindowCentered,
		JS:               desktopBridgeJS(l.server.BaseURL()),
	})
	// The toolkit paints its own background under the page, which would frame
	// the rounded splash in the theme colour
	win.RegisterHook(events.Common.WindowShow, func(*application.WindowEvent) {
		gtkwin.MakeTransparent(win.NativeWindow())
	})
	l.attachCloseConfirm(win)
	return win
}

func (l *launcher) newMainWindow() *application.WebviewWindow {
	win := l.app.Window.NewWithOptions(application.WebviewWindowOptions{
		Name:             mainWindowName,
		Title:            "UN1CA Build",
		Width:            1400,
		Height:           900,
		MinWidth:         420,
		MinHeight:        640,
		URL:              l.mainURL(),
		BackgroundColour: application.NewRGB(0, 0, 0),
		InitialPosition:  application.WindowCentered,
		// The interface calls this bridge to keep the exit dialog translated,
		// and it has to work from the container origin too
		JS: desktopBridgeJS(l.server.BaseURL()),
	})
	l.attachCloseConfirm(win)
	return win
}

// mainURL is the embedded interface when the binary carries one, and the
// frontend container otherwise
func (l *launcher) mainURL() string {
	if l.cfg.EmbeddedUI {
		return l.server.BaseURL() + "/"
	}
	return l.cfg.FrontendURL
}

func desktopBridgeJS(baseURL string) string {
	payload, _ := json.Marshal(baseURL)
	return `(function () {
  var base = ` + string(payload) + `;
  function post(body) {
    try {
      fetch(base + '/bridge/language', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      }).catch(function () {});
    } catch (e) {}
  }
  function exit(body) {
    try {
      fetch(base + '/action/exit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      }).catch(function () {});
    } catch (e) {}
  }
  window.desktopApi = {
    setLanguage: function (lang) { post({ lang: String(lang || '') }); },
    setI18nStrings: function (strings) { post({ strings: strings || {} }); }
  };

  function renderExitPrompt(t) {
    var old = document.getElementById('unica-exit-overlay');
    if (old) old.remove();

    var css = document.createElement('style');
    css.textContent = [
      '#unica-exit-overlay{position:fixed;inset:0;z-index:2147483647;display:flex;',
      'border-radius:0;',
      'align-items:center;justify-content:center;padding:24px;',
      'background:rgba(0,0,0,0.62);backdrop-filter:blur(3px);',
      "font-family:'SamsungOne','Segoe UI',Roboto,sans-serif;}",
      '#unica-exit-card{width:100%;max-width:380px;border-radius:26px;padding:26px 24px 18px;',
      'background:#1c1c1e;border:1px solid rgba(255,255,255,0.06);color:#fbfbfb;',
      'box-shadow:0 24px 70px rgba(0,0,0,0.55);}',
      "#unica-exit-card h3{margin:0;font-size:21px;font-weight:700;text-align:center;",
      "font-family:'SamsungSharpSans','SamsungOne',sans-serif;}",
      '#unica-exit-card p{margin:12px 0 0;font-size:14px;line-height:1.5;text-align:center;',
      'color:rgba(252,252,252,0.62);}',
      '#unica-exit-actions{display:flex;gap:10px;margin-top:24px;}',
      '#unica-exit-actions button{flex:1;height:44px;border-radius:22px;border:0;cursor:pointer;',
      'font-size:15px;font-weight:700;font-family:inherit;transition:background 140ms ease;}',
      '#unica-exit-cancel{background:#242427;color:#fbfbfb;}',
      '#unica-exit-cancel:hover{background:#2e2e32;}',
      '#unica-exit-confirm{background:#1259d1;color:#fff;}',
      '#unica-exit-confirm:hover{background:#1063e6;}'
    ].join('');

    var overlay = document.createElement('div');
    overlay.id = 'unica-exit-overlay';
    if (document.documentElement.getAttribute('data-unica-window') === 'splash') {
      overlay.style.inset = '26px';
      overlay.style.borderRadius = '26px';
    }
    overlay.appendChild(css);

    var card = document.createElement('div');
    card.id = 'unica-exit-card';
    var title = document.createElement('h3');
    title.textContent = t.title || '';
    card.appendChild(title);
    [t.message, t.detail].forEach(function (line) {
      if (!line) return;
      var p = document.createElement('p');
      p.textContent = line;
      card.appendChild(p);
    });

    var actions = document.createElement('div');
    actions.id = 'unica-exit-actions';
    var cancelBtn = document.createElement('button');
    cancelBtn.id = 'unica-exit-cancel';
    cancelBtn.textContent = t.cancel || 'Cancel';
    var confirmBtn = document.createElement('button');
    confirmBtn.id = 'unica-exit-confirm';
    confirmBtn.textContent = t.exit || 'Exit';
    actions.appendChild(cancelBtn);
    actions.appendChild(confirmBtn);
    card.appendChild(actions);
    overlay.appendChild(card);

    function close(ok) {
      document.removeEventListener('keydown', onKey, true);
      overlay.remove();
      exit({ ok: !!ok });
    }
    function onKey(event) {
      if (event.key === 'Escape') close(false);
      if (event.key === 'Enter') close(true);
    }
    cancelBtn.addEventListener('click', function () { close(false); });
    confirmBtn.addEventListener('click', function () { close(true); });
    overlay.addEventListener('click', function (event) { if (event.target === overlay) close(false); });
    document.addEventListener('keydown', onKey, true);

    document.body.appendChild(overlay);
    confirmBtn.focus();
    exit({ shown: true });
  }

  try {
    var events = new EventSource(base + '/events');
    events.addEventListener('exit-request', function (event) {
      try { renderExitPrompt(JSON.parse(event.data) || {}); } catch (e) {}
    });
  } catch (e) {}
})();`
}

// attachCloseConfirm turns a window close into the same confirmation Electron
// showed, because closing the window also stops every build container
func (l *launcher) attachCloseConfirm(win *application.WebviewWindow) {
	win.RegisterHook(events.Common.WindowClosing, func(e *application.WindowEvent) {
		if l.quitApproved.Load() || l.shuttingDown.Load() {
			return
		}
		e.Cancel()
		if l.dialogOpen.CompareAndSwap(false, true) {
			go l.askExit(win)
		}
	})
}

// askExit draws the confirmation inside the window so it carries the app's own
// design, and only falls back to a system dialog when the page does not answer
func (l *launcher) askExit(win *application.WebviewWindow) {
	texts := l.exitTexts()
	shown, answer := l.server.BeginExitPrompt()

	l.server.Publish("exit-request", map[string]string{
		"title":   texts.title,
		"message": texts.message,
		"detail":  texts.detail,
		"cancel":  texts.cancel,
		"exit":    texts.exit,
	})

	select {
	case <-shown:
	case <-time.After(1500 * time.Millisecond):
		l.server.EndExitPrompt()
		application.InvokeAsync(func() { l.askExitNative(win) })
		return
	}

	ok := <-answer
	l.server.EndExitPrompt()
	l.dialogOpen.Store(false)
	if ok {
		l.quitApproved.Store(true)
		l.shutdown()
	}
}

func (l *launcher) askExitNative(win *application.WebviewWindow) {
	texts := l.exitTexts()
	dialog := l.app.Dialog.Question()
	dialog.SetTitle(texts.title)
	dialog.SetMessage(texts.message + "\n\n" + texts.detail)
	dialog.AttachToWindow(win)

	cancel := dialog.AddButton(texts.cancel)
	cancel.SetAsCancel()
	cancel.OnClick(func() { l.dialogOpen.Store(false) })

	confirm := dialog.AddButton(texts.exit)
	confirm.SetAsDefault()
	confirm.OnClick(func() {
		l.dialogOpen.Store(false)
		l.quitApproved.Store(true)
		go l.shutdown()
	})

	dialog.Show()
}

type exitTexts struct {
	title, message, detail, cancel, exit string
}

// exitTexts prefers the strings the web UI pushed over the bridge, so the
// dialog matches whatever language the user picked in the app
func (l *launcher) exitTexts() exitTexts {
	l.i18nMu.RLock()
	defer l.i18nMu.RUnlock()

	pick := func(key string) string {
		if v, ok := l.i18n[key]; ok && v != "" {
			return v
		}
		return i18n.Get(l.language, key)
	}
	return exitTexts{
		title:   pick("exitConfirmTitle"),
		message: pick("exitConfirmMessage"),
		detail:  pick("exitConfirmDetail"),
		cancel:  pick("cancel"),
		exit:    pick("exit"),
	}
}

func (l *launcher) setLanguage(lang string, strings map[string]string) {
	l.i18nMu.Lock()
	if lang != "" {
		if len(lang) >= 2 && lang[:2] == "ru" {
			l.language = "ru"
		} else {
			l.language = "en"
		}
	}
	for key, value := range strings {
		if value != "" {
			l.i18n[key] = value
		}
	}
	current := l.language
	l.i18nMu.Unlock()
	l.publishTexts(current)
}

// publishTexts keeps the startup screen on the same language as everything else
func (l *launcher) publishTexts(language string) {
	l.server.SetTexts(language, i18n.UI(language), i18n.Messages(language))
}

func (l *launcher) focusForeground() {
	if l.main != nil {
		l.main.Show()
		l.main.Focus()
		return
	}
	if l.splash != nil {
		l.splash.Show()
		l.splash.Focus()
	}
}

func (l *launcher) runStartup() {
	ctx := context.Background()
	if err := l.orch.Startup(ctx); err != nil {
		l.reportDeadEnd(err)
		return
	}
	l.app.Event.Emit("startup:done")
	l.openMainWindow()
}

func (l *launcher) runFix(kind string) {
	ctx := context.Background()
	if err := l.orch.ApplyFix(ctx, kind); err != nil {
		l.reportDeadEnd(err)
		return
	}
	l.runStartup()
}

// reportDeadEnd makes sure a failure the sequence did not already publish still
// reaches the screen, so the retry button comes back instead of the last
// progress line sitting there forever
func (l *launcher) reportDeadEnd(err error) {
	if l.shuttingDown.Load() || err == nil {
		return
	}
	if l.orch.Emitter().Failed() {
		return
	}
	l.orch.Emitter().Fail(orch.Failure{Message: err.Error(), Code: "startup_failed"})
}

func (l *launcher) openMainWindow() {
	if l.main != nil {
		l.focusForeground()
		return
	}
	l.main = l.newMainWindow()
	if l.splash != nil {
		splash := l.splash
		l.splash = nil
		// The splash close must not trigger the exit confirmation
		l.quitApproved.Store(true)
		splash.Close()
		l.quitApproved.Store(false)
	}
}

// shutdown stops the stack with the splash screen showing progress, then quits
func (l *launcher) shutdown() {
	if !l.shuttingDown.CompareAndSwap(false, true) {
		return
	}
	if !l.cfg.ComposeDownOnQuit {
		l.app.Quit()
		return
	}

	l.orch.Emitter().SetShutdown(true)
	l.server.SetMode("shutdown")
	if l.main != nil {
		l.main.Hide()
	}
	if l.splash == nil {
		l.splash = l.newSplashWindow(l.server.BaseURL())
	} else {
		l.splash.Show()
		l.splash.Focus()
	}
	l.orch.Emitter().Shutdown(0, "Stopping...")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	done := make(chan struct{})
	go func() {
		defer close(done)
		l.orch.ComposeDown(ctx)
	}()

	select {
	case <-done:
	case <-time.After(l.cfg.ForceKillTimeout):
		killCtx, killCancel := context.WithTimeout(context.Background(), 60*time.Second)
		l.orch.ComposeForceKill(killCtx)
		killCancel()
	}

	l.orch.StopKeepalive()
	l.quitApproved.Store(true)
	l.app.Quit()
}

func init() {
	// Wails writes its own diagnostics; keep ours on the same stream
	log.SetOutput(os.Stderr)
	log.SetFlags(0)
	log.SetPrefix(fmt.Sprintf("[unica-wb] "))
}
