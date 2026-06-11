const sections = [
  'Organizations',
  'Workspaces',
  'Members',
  'Tasks',
  'Decisions',
  'Memory Search',
  'Provider Keys',
  'Audit Logs',
  'Deployment Settings',
]

export default function AdminHome() {
  return (
    <main className="min-h-screen p-8">
      <section className="mx-auto max-w-6xl">
        <p className="text-sm uppercase tracking-[0.3em] text-cyan-300">Enterprise Console</p>
        <h1 className="mt-4 text-4xl font-bold text-white">TeamMind Admin</h1>
        <p className="mt-3 max-w-2xl text-slate-300">
          Operator surface for tenant management, AI provider controls, audit review, and private
          deployment settings.
        </p>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {sections.map((section) => (
            <article key={section} className="rounded-2xl border border-slate-700 bg-slate-900 p-5">
              <h2 className="text-lg font-semibold text-white">{section}</h2>
              <p className="mt-2 text-sm text-slate-400">Enterprise-ready placeholder module.</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  )
}