import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import type { Resource } from 'i18next'

// Vite glob import: eagerly load all locale JSON files at build time
const localeModules = import.meta.glob('./locales/**/*.json', { eager: true }) as Record<string, { default: Record<string, string> }>

function buildResources(): Resource {
  const resources: Resource = {}
  for (const [path, module] of Object.entries(localeModules)) {
    // path format: ./locales/en/common.json or ./locales/zh-CN/layout.json
    const match = path.match(/\.\/locales\/([^/]+)\/([^/]+)\.json$/)
    if (!match) continue
    const [, lang, namespace] = match
    if (!resources[lang]) resources[lang] = {}
    resources[lang][namespace] = module.default
  }
  return resources
}

const savedLang = typeof window !== 'undefined'
  ? localStorage.getItem('ksm-lang') || 'en'
  : 'en'

i18n
  .use(initReactI18next)
  .init({
    resources: buildResources(),
    lng: savedLang,
    fallbackLng: 'en',
    defaultNS: 'common',
    ns: ['common', 'layout', 'dashboard', 'graph', 'knowledgeBase', 'noteDetail', 'ingest', 'search', 'searchLexicon', 'settings', 'auth', 'apiManagement', 'ontology'],
    interpolation: { escapeValue: false },
  })

// Persist language changes to localStorage
i18n.on('languageChanged', (lng) => {
  if (typeof window !== 'undefined') {
    localStorage.setItem('ksm-lang', lng)
  }
})

export default i18n
