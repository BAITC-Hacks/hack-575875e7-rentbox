import { Geist_Mono, Inter } from "next/font/google"

import "@workspace/ui/globals.css"
import "./dashboard.css"
import "./dashboard-v2.css"
import "./appearance.css"
import { AppearanceProvider } from "@/components/appearance-provider"
import { LocaleProvider } from "@/components/locale-provider"
import { ThemeProvider } from "@/components/theme-provider"
import { cn } from "@workspace/ui/lib/utils"

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
})

const fontMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
})

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="ru"
      suppressHydrationWarning
      className={cn(
        "antialiased",
        fontMono.variable,
        "font-sans",
        inter.variable
      )}
    >
      <body>
        <ThemeProvider
          defaultTheme="light"
          enableSystem={false}
          storageKey="windcast.theme"
        >
          <LocaleProvider>
            <AppearanceProvider>{children}</AppearanceProvider>
          </LocaleProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
