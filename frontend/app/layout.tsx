import './globals.css'

import type { ReactNode } from 'react'

export const metadata = {
  title: 'TeamMind Admin',
  description: 'Enterprise admin console for TeamMind',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}