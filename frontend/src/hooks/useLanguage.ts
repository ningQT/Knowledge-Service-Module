import { useTranslation } from 'react-i18next'
import { useCallback } from 'react'

export function useLanguage() {
  const { i18n } = useTranslation()

  const language = i18n.language

  const changeLanguage = useCallback((lng: string) => {
    i18n.changeLanguage(lng)
  }, [i18n])

  const toggleLanguage = useCallback(() => {
    const next = i18n.language === 'en' ? 'zh-CN' : 'en'
    i18n.changeLanguage(next)
  }, [i18n])

  return { language, changeLanguage, toggleLanguage }
}
