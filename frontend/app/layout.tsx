import '@/styles/globals.css'
import type { Metadata } from 'next'
import { Github } from 'lucide-react'
import { AuthProvider } from '@/contexts/AuthContext'

export const metadata: Metadata = {
  metadataBase: new URL("https://group-documents.pgdev.com.br"),
  title: "BrainHub: ask across your files, with sources",
  description:
    "Ask questions across PDFs, images, audio, video and web pages. Inspect source passages, compare document dates and review conflicting information. Try the fictional sample library without an account.",
  authors: [{ name: "Pedro Gomes" }],
  creator: "Pedro Gomes",
  // Sem openGraph/twitter o link vira URL crua quando compartilhado.
  openGraph: {
    type: "website",
    url: "https://group-documents.pgdev.com.br",
    siteName: "BrainHub",
    locale: "en_US",
    title: "BrainHub: ask across your files, with sources",
    description:
      "Ask questions across PDFs, images, audio, video and web pages. Inspect source passages, compare document dates and review conflicting information. Try the fictional sample library without an account.",
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "BrainHub: answers across your files with source references" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "BrainHub: ask across your files, with sources",
    description:
      "Ask questions across PDFs, images, audio, video and web pages. Inspect source passages, compare document dates and review conflicting information. Try the fictional sample library without an account.",
    images: ["/og.png"],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-dvh bg-neutral-950 text-white font-sans antialiased">
        <div className="app-bg" aria-hidden />
        <div className="app-grid" aria-hidden />
        <AuthProvider>{children}</AuthProvider>
        {/* Sem e-mail nem links de contato, de proposito: so o link do repositorio. */}
        <footer className="border-t border-white/10 py-6 text-xs text-neutral-400">
          <div className="max-w-7xl mx-auto px-4 sm:px-8 flex flex-col sm:flex-row items-center justify-between gap-3">
            <p>
              Built by <span className="font-medium text-neutral-200">Pedro Gomes</span>
            </p>
            <a
              href="https://github.com/devpedrogomes/group-documents"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 hover:text-white transition-colors"
            >
              <Github className="h-3.5 w-3.5" aria-hidden /> GitHub
            </a>
          </div>
        </footer>
      </body>
    </html>
  )
}
