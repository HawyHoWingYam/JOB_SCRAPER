// apps/frontend/src/components/Navigation.tsx
import React from 'react';
import Link from 'next/link';

export default function Navigation() {
  return (
    <nav className="bg-blue-700 text-white shadow-md">
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex justify-between h-16">
          <div className="flex">
            <div className="flex-shrink-0 flex items-center">
              <Link href="/" className="text-xl font-bold">
                Job Scraper
              </Link>
            </div>
            <div className="ml-10 flex items-center space-x-4">
              <Link href="/" className="px-3 py-2 rounded-md hover:bg-blue-600">
                Home
              </Link>
              <Link href="/jobs" className="px-3 py-2 rounded-md hover:bg-blue-600">
                Jobs
              </Link>
            </div>
          </div>
          
          {/* Login/Signup Buttons */}
          <div className="flex items-center space-x-2">
            <Link href="/auth/login" className="px-3 py-2 rounded-md hover:bg-blue-600">
              Login
            </Link>
            <Link href="/auth/signup" className="px-3 py-2 rounded-md hover:bg-blue-600">
              Sign Up
            </Link>
          </div>
        </div>
      </div>
    </nav>
  );
}