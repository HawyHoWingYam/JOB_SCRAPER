// app/layout.js
import { Inter } from 'next/font/google';
import { Providers } from './providers';
import './globals.css';

// Use the Inter font
const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
});

// Metadata should be in a server component
export const metadata = {
  title: 'Job Scraper',
  description: 'Find and analyze job opportunities efficiently',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <Providers>
          <main>{children}</main>
        </Providers>
      </body>
    </html>
  );
}