import './globals.css'

import type { ReactNode } from 'react'

export const metadata = {
  title: 'Rhapsody Admin',
  description: 'Bilingual enterprise admin console for Rhapsody',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
