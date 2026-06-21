import Link from 'next/link'
import { notFound } from 'next/navigation'

import { getMessages, isLocale, oppositeLocale } from '../../lib/i18n'

export default function AdminHome({ params }: { params: { locale: string } }) {
  if (!isLocale(params.locale)) {
    notFound()
  }
  const locale = params.locale
  const copy = getMessages(locale).home
  const otherLocale = oppositeLocale(locale)

  return (
    <main className="min-h-screen p-8">
      <section className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm uppercase tracking-[0.3em] text-cyan-300">{copy.eyebrow}</p>
          <Link
            className="rounded-full border border-cyan-300/40 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:border-cyan-200 hover:bg-cyan-300/10"
            href={`/${otherLocale}`}
          >
            {copy.language}: {copy.switchTo}
          </Link>
        </div>
        <h1 className="mt-4 text-4xl font-bold text-white">{copy.title}</h1>
        <p className="mt-3 max-w-2xl text-slate-300">{copy.description}</p>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {copy.sections.map((section) => (
            <article key={section} className="rounded-2xl border border-slate-700 bg-slate-900 p-5">
              <h2 className="text-lg font-semibold text-white">{section}</h2>
              <p className="mt-2 text-sm text-slate-400">{copy.placeholder}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  )
}
