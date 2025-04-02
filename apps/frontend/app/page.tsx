'use client';

import { useState, useEffect } from 'react';

export default function Home() {
  const [apiStatus, setApiStatus] = useState<string>('Loading...');
  const [apiTimestamp, setApiTimestamp] = useState<number | null>(null);
  const [isError, setIsError] = useState<boolean>(false);

  useEffect(() => {
    const checkApiHealth = async () => {
      try {
        const response = await fetch('http://localhost:3001/health', {
          method: 'GET',
          headers: {
            'Content-Type': 'application/json',
          },
          // Add this to handle credentials if needed
          // credentials: 'include',
        });
        
        if (!response.ok) {
          throw new Error(`HTTP error! Status: ${response.status}`);
        }
        
        const data = await response.json();
        setIsError(false);
        setApiStatus(data.status);
        setApiTimestamp(data.timestamp);
      } catch (error) {
        console.error('Error checking API health:', error);
        setIsError(true);
        setApiStatus('Error connecting to API');
      }
    };

    checkApiHealth();
  }, []);

  return (
    <main className="container">
      <div className="main">
        <h1 className="title">
          Job Scraper Platform
        </h1>

        <div className="description">
          <p>API Status: <span className={isError ? "error-text" : "success-text"}>{apiStatus}</span></p>
          {apiTimestamp && (
            <p>Timestamp: {new Date(apiTimestamp).toLocaleString()}</p>
          )}
        </div>
      </div>
    </main>
  );
}