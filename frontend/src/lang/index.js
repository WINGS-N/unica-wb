import { ref } from 'vue'
import en from './en.json'
import ru from './ru.json'

export const SUPPORTED_LANGS = ['en', 'ru']

export const I18N = { en, ru }

const STORAGE_LANGUAGE = 'un1ca:lang'

export const language = ref(
  SUPPORTED_LANGS.includes(localStorage.getItem(STORAGE_LANGUAGE)) ? localStorage.getItem(STORAGE_LANGUAGE) : 'en'
)

// Fallback to english when the selected locale has no key, then to the key
// itself so a missing string is visible instead of blank
export function t(key, vars) {
  let value = I18N[language.value]?.[key] || I18N.en[key] || key
  if (vars) {
    for (const [name, replacement] of Object.entries(vars)) {
      value = value.replaceAll(`{${name}}`, String(replacement))
    }
  }
  return value
}

export function hasTranslation(key) {
  return Boolean(I18N[language.value]?.[key] || I18N.en[key])
}

export function setLanguage(next) {
  const safe = SUPPORTED_LANGS.includes(next) ? next : 'en'
  language.value = safe
  localStorage.setItem(STORAGE_LANGUAGE, safe)
  try {
    window.desktopApi?.setLanguage?.(safe)
    window.desktopApi?.setI18nStrings?.({
      exitConfirmTitle: t('exitConfirmTitle'),
      exitConfirmMessage: t('exitConfirmMessage'),
      exitConfirmDetail: t('exitConfirmDetail'),
      cancel: t('cancel'),
      exit: t('exit')
    })
  } catch {
    // desktop bridge missing (plain browser) -> nothing to sync
  }
}
