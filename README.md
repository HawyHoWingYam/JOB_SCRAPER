# Job Scraper Platform

A recruitment platform built with Next.js (frontend), Nest.js (backend), PostgreSQL (database), and Python (web scraping and AI services).

## Getting Started

### Prerequisites
- Node.js (v18+)
- npm
- PostgreSQL

### Setup Database
1. Create a PostgreSQL database named `job_scraper`
2. Configure database connection in `apps/backend/.env`

### Install Dependencies
```bash
npm install
```

### Development
Run both frontend and backend concurrently:
```bash
npm run dev
```

Or individually:
```bash
# Frontend only
npm run dev:frontend

# Backend only
npm run dev:backend
```

### Accessing the Applications
- Frontend: http://localhost:3000
- Backend API: http://localhost:3001/api
- Health check: http://localhost:3001/api/health