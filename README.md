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
npm run dev

# Backend only
npm run start:dev
```

1. npm run start:dev
2. npm run dev 

### Accessing the Applications
- Frontend: http://localhost:3000
- Backend API: http://localhost:3001/api
- Health check: http://localhost:3001/api/health




https://www.glassdoor.com.hk/Job/hong-kong-jobs-SRCH_IL.0,9_IN106.htm?sortBy=date_desc

https://hk.indeed.com/jobs?l=Hong%20Kong%20Island&radius=100&sort=date
https://hk.indeed.com/jobs?l=Kowloon&radius=100&sort=date
https://hk.indeed.com/jobs?l=New%20Territories&radius=100&sort=date


Get Header : 

- JobsDB
python -m job_scraper.__init__ source_platform=1, start_page=1, end_page=20, method=selenium, save=True

- LinkedIn
python -m job_scraper.__init__ source_platform=4, start_page=1, end_page=40, method=selenium, save=True


Get Details :
- LinkedIn
python -m job_scraper.__init__ source_platform=4, quantity=2000, method=selenium,  save=True, filter=N/A, workers=5

- JobsDB
python -m job_scraper.__init__ source_platform=1, quantity=40000, method=selenium, save=True, filter=N/A, workers=5

docker-compose up -d