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

Get Header : 

- JobsDB
python -m job_scraper.__init__ source_platform=1, start_page=1, end_page=2, method=selenium, job_class=18, save=True

- LinkedIn
python -m job_scraper.__init__ source_platform=4, start_page=1, end_page=40, method=selenium, save=True


Get Details :
- LinkedIn
python -m job_scraper.__init__ source_platform=4, quantity=500, method=selenium,  save=True, filter=all, workers=1

- JobsDB
python -m job_scraper.__init__ source_platform=1, quantity=10, method=selenium, job_class=18, save=True, filter=N/A, workers=5