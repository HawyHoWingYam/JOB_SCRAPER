
/** @type {import('next').NextConfig} */

const nextConfig = {
    reactStrictMode: true,
    swcMinify: true,
    
    // Enable image optimization for job listings and company logos
    images: {
      domains: [
        'localhost', // For development
        // Add production domains when available
        'example.com',
        'jobimages.com',
        'companylogos.com',
      ],
      formats: ['image/avif', 'image/webp'],
    },
    
    // Configure environment variables
    env: {
      API_URL: process.env.API_URL || 'http://localhost:3001', // Default to localhost for development
    },
    
    // Enable experimental features if needed
    experimental: {
      // serverActions: true,
      // esmExternals: true,
    },
    
    // Configure redirects for user experience
    async redirects() {
      return [
        {
          source: '/jobs',
          destination: '/',
          permanent: true,
        },
      ];
    },
    
    // Configure headers for security and performance
    async headers() {
      return [
        {
          // Apply these headers to all routes
          source: '/(.*)',
          headers: [
            {
              key: 'X-Content-Type-Options',
              value: 'nosniff',
            },
            {
              key: 'X-XSS-Protection',
              value: '1; mode=block',
            },
            {
              key: 'X-Frame-Options',
              value: 'DENY',
            },
          ],
        },
      ];
    },
  
    // Configure webpack if needed for specific packages
    webpack: (config, { buildId, dev, isServer, defaultLoaders, webpack }) => {
      // Custom webpack configuration if needed
      
      return config;
    },
  };
  
  module.exports = nextConfig;