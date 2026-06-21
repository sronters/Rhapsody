import en from '../messages/en.json'
import ru from '../messages/ru.json'

export const locales = ['en', 'ru'] as const
export type Locale = (typeof locales)[number]

const messages = { en, ru }

export function isLocale(value: string): value is Locale {
  return locales.includes(value as Locale)
}

export function getMessages(locale: Locale) {
  return messages[locale]
}

export function oppositeLocale(locale: Locale): Locale {
  return locale === 'en' ? 'ru' : 'en'
}
