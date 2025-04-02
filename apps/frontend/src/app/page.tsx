// ./apps/frontend/src/app/page.tsx
'use client';

import { useEffect, useState } from 'react';

export default function Home() {
  const [apiStatus, setApiStatus] = useState<string>('Checking API...');

  useEffect(() => {
    const checkApiStatus = async () => {
      try {
        const response = await fetch('http://localhost:3001/api/health');
        const data = await response.json();
        setApiStatus(`API Status: ${data.status}, Last checked: ${data.timestamp}`);
      } catch (error) {
        setApiStatus('API Error: Could not connect to the server');
        console.error('Error connecting to API:', error);
      }
    };

    checkApiStatus();
  }, []);

  return (
    <main className="flex min-h-screen flex-col items-center justify-between p-24">
      <div className="z-10 max-w-5xl w-full items-center justify-between font-mono text-sm flex flex-col">
        <h1 className="text-4xl font-bold mb-6">Job Scraper Platform</h1>
        <p className="text-xl mb-4">Welcome to the Job Scraper Platform</p>
        <div className="p-4 border rounded bg-gray-100 w-full max-w-md">
          <p className="font-medium">{apiStatus}</p>
        </div>
      </div>
    </main>
  );
}