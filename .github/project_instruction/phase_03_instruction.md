## Phase 3: Project Setup and Scaffolding

**Objective & Direction:** Set up the development environment and create the initial scaffold for the project’s codebase. The aim is to bootstrap the Next.js and Nest.js applications (and prepare Python environments) so that you have a runnable “Hello World” in each part. This phase establishes the base folder hierarchy and configuration files, which all further development will build upon.

**Key Activities:**

- **Initialize Git Repository:** Create a git repository (if you haven’t already) at the project root. This will track all changes in frontend, backend, and services folders together (monorepo setup).
    
- **Scaffold Next.js Frontend:** Use the Next.js CLI or manual setup to create a new Next.js project in the `frontend` folder. For example, run `npx create-next-app@latest frontend --typescript` to generate a Next.js TypeScript project. This will create the basic file structure (pages, `tsconfig.json`, etc.). If you have multiple frontends, run this for each (e.g. `frontend-client`, `frontend-portal`, etc.), or create one and plan to branch out later.
    
- **Scaffold Nest.js Backend:** Use the Nest CLI to create a new Nest project in the `backend` folder: `nest new backend`. This will generate a standard Nest.js structure with an initial controller, service, and module. Ensure to choose TypeScript (Nest defaults to TS) and install any initial dependencies. Remove or adjust any boilerplate not needed (for example, Nest creates a sample `AppController` and `AppService` — you can keep these as a health check endpoint or placeholder).
    
- **Setup Shared Configurations:** Add configurations that apply project-wide. For instance, create a root `.gitignore` to ignore `node_modules`, environment files, etc., and perhaps a README at the root with project overview. If using a monorepo tool (like Nx or Yarn workspaces), configure that now to manage dependencies across packages (optional; for a solo project, you can manage each subproject’s dependencies separately too).
    
- **Install Dependencies:** In the frontend, install any initial UI/library dependencies you anticipate (e.g. a component library or axios for API calls). In the backend, install database client or ORM (e.g. `@nestjs/typeorm` plus `pg` for PostgreSQL if using TypeORM). In Python service folders, set up a virtual environment and create a `requirements.txt` (initially maybe just `scrapy` or `requests` for the crawler, and necessary ML libraries for AI matching, to be filled as you implement).
    
- **Verify Hello World:** Run the frontend and backend to ensure they start without errors. For Next.js, `npm run dev` (which by default runs on localhost:3000) should show the default Next.js welcome page. For Nest.js, `npm run start:dev` (default on localhost:3001 or 3000) should display a basic “Hello World” JSON from the default controller. This confirms that the scaffolding is successful and the environment is ready for development.
    

**Types of Files to be Created:**

- **Configuration files:** e.g. `package.json` (for both front-end and back-end), `tsconfig.json`, `.eslintrc.js` or `.prettierrc` (if using linting/formatting tools), etc.
    
- **Boilerplate code files:** Next.js starter files (`pages/index.tsx`, etc.), Nest.js starter files (`main.ts`, `app.module.ts`, `app.controller.ts`, `app.service.ts`).
    
- **Environment files:** Create sample `.env` files for development (e.g. `backend/.env`) to store config like database URL, API keys, etc. (You might fill these in Phase 4 when connecting the database and services).
    
- **Readme/Documentation:** Basic usage instructions in a `README.md` at root or within each sub-project (frontend, backend) explaining how to run them.
    

**File Structure & Key Files (after Scaffolding):**

The repository now has a baseline structure. Key files and folders created include:

- **`/frontend/`** – Next.js front-end project folder.
    
    - `pages/index.tsx`: Main page (Next.js default homepage – will be replaced with actual content later).
        
    - `pages/api/` (if present): Next.js API routes (not needed since we use Nest.js for API, but Next scaffolding includes an example).
        
    - `public/`: Static assets (contains Next.js favicon, can store images, etc.).
        
    - `styles/`: Global CSS or styling (e.g. `globals.css`).
        
    - `package.json`: Frontend project dependencies and scripts (includes Next.js, React, etc.).
        
    - `tsconfig.json`: TypeScript configuration for the frontend.
        
- **`/backend/`** – Nest.js back-end project folder.
    
    - `src/main.ts`: Entry point of the Nest application (bootstraps the NestJS server on a given port).
        
    - `src/app.module.ts`: Root application module that imports other feature modules (currently includes just the default AppModule).
        
    - `src/app.controller.ts`: A sample controller (from Nest scaffold) that can be used to test the API (e.g. GET `/` returns "Hello World").
        
    - `src/app.service.ts`: A sample service used by the controller (for demo purposes).
        
    - `package.json`: Backend project dependencies (NestJS framework, etc.) and scripts.
        
    - `nest-cli.json` & `tsconfig.json`: Nest CLI config and TypeScript config for backend.
        
- **`/services/crawler/`** – Python crawler service folder.
    
    - `requirements.txt`: Python dependencies for the web scraper (e.g. will list `scrapy` or other libraries once decided).
        
    - (At this stage, possibly just an empty folder or a simple placeholder script like `crawler.py`.)
        
- **`/services/ai_matching/`** – Python AI service folder.
    
    - `requirements.txt`: Python dependencies for AI matching (to be filled, e.g. NLP libraries).
        
    - (Likely empty or a placeholder script for now.)
        
- **Root files:**
    
    - `.gitignore`: Ensures node_modules, Python env, and secrets are not committed.
        
    - `README.md`: Project overview and instructions on how to run frontend and backend (will be updated as the project progresses).
        

This scaffold provides a starting template. **Purpose of key files:** The Next.js files are placeholders for pages and will host the UI; the Nest.js files confirm the server runs and will be expanded to full APIs. The folder hierarchy separates concerns: front-end vs back-end vs services, aligning with a modular architecture.
