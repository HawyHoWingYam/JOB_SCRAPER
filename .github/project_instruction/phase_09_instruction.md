
## Phase 9: Deployment and Project Launch

**Objective & Direction:** Prepare the application for deployment and launch the prototype in an environment where it can be accessed (by you or stakeholders) without a development setup. Even if it’s not a production release, deploying the prototype will allow real-world usage and feedback. This phase also includes final documentation and planning for future improvements (since there’s no strict deadline, you may continue refining after initial launch). Emphasis is on **DevOps** practices: containerizing the app, setting up hosting, and ensuring each module can run in the target environment.

**Key Activities:**

- **Set Up Deployment Environment:** Decide where to host the different components:
    
    - A simple approach for a prototype is to use a single VPS or cloud instance (e.g., an AWS EC2, DigitalOcean droplet) and run everything (database, backend, frontend, and services) on it, possibly using Docker to containerize each.
        
    - Alternatively, use specialized hosting: Frontend on a service like Vercel (since it’s Next.js), Backend on a node-friendly host or Heroku (Heroku no free tier now, but maybe render.com), and Python services on a small VM or as background processes.
        
    - Database can be a managed PostgreSQL service or a Docker container on the same host.
        
- **Containerization (Optional but common):** Create Dockerfiles for each component to ensure consistent deployment:
    
    - **Dockerfile for Frontend:** Based on node:alpine, install deps, build the Next.js app for production (`npm run build`), then use `npm start` or export as static if using purely static export. Alternatively, for Vercel, just push code and let it handle.
        
    - **Dockerfile for Backend:** Based on node, copy source, install, build TS (`npm run build` in Nest), and run `node dist/main.js`. Include steps to copy or include `.env.production` for config.
        
    - **Dockerfile for Crawler and AI services:** Based on python:3.x, copy code, install requirements, and set entrypoints (for crawler, the entry might be the python script on a schedule; for AI service, run the Flask app).
        
    - Create a `docker-compose.yml` that defines all services: frontend, backend, crawler, AI, and a PostgreSQL image. This way, you (or others) can spin up the entire system with one command. Map appropriate ports (e.g., front (Next.js) on 3000, backend (Nest.js) on 3001, maybe AI service on 5000, and Postgres on 5432).
        
- **Configure Environment for Production:** Set appropriate environment variables and settings for the deployed environment:
    
    - Enable production optimizations (e.g., `NODE_ENV=production`).
        
    - Set up a secure configuration (strong JWT secret, proper database URLs).
        
    - In Next.js, ensure API URL points to the deployed backend’s URL.
        
    - Handle CORS in the Nest.js app (allow the domain where front-end is hosted).
        
    - If deploying on separate domains, you might set up a reverse proxy or configure allowed origins accordingly.
        
- **Deploy the Services:** Launch the containers or upload code to hosts:
    
    - If using Docker Compose on a single VM: copy the docker-compose and related Dockerfiles to the server and run it. Verify each service comes up and can talk to each other (the compose network links them by service name).
        
    - If using different hosts: deploy each accordingly (for example, push front-end to Vercel by connecting the Git repo, deploy backend by pushing to Heroku or running on a server, etc., and update env variables on each).
        
    - Run database migrations or schema creation on the production DB.
        
    - Seed the production database with some initial data if needed (maybe run the crawler once to populate some jobs, create an admin user, etc.).
        
- **Final Verification:** After deployment, do a final test in the live environment:
    
    - Access the front-end via its URL, go through key flows to ensure everything works outside of localhost.
        
    - Check logs of backend and services to catch any runtime errors (sometimes small differences in prod config can cause issues).
        
    - Monitor performance (make sure pages load in reasonable time, no errors).
        
- **Documentation & Handover:** Now that the project is live (prototype live), finalize documentation:
    
    - Update README with deployment instructions and links (e.g., “Front-end is deployed at ___, Backend API at ___”).
        
    - Document how to run the Docker compose or how to start each service in production.
        
    - Provide credentials for any test accounts on the live system (e.g., an admin login to demonstrate admin features).
        
    - Write a short **technical report or summary** of the project (could be in `docs/summary.md` or just in README) describing architecture, what was achieved, and ideas for future extensions.
        
- **Planning Next Steps:** Although not a part of deployment, it’s good to list future improvements now:
    
    - For example, more advanced security (OAuth, etc.), scaling considerations (maybe splitting services further or adding caching), more AI features, etc. This is not required in the plan, but as a solo dev, keeping a backlog of improvements is useful after launch.
        

**Types of Files to be Created or Modified:**

- **Dockerfiles:** `frontend/Dockerfile`, `backend/Dockerfile`, `services/crawler/Dockerfile`, `services/ai_matching/Dockerfile`.
    
- **Docker Compose:** `docker-compose.yml` at project root defining how containers work together.
    
- **Environment files for production:** e.g., `.env.production` variants or configuration in your deployment platform’s interface.
    
- **Deployment scripts:** If not using Docker, maybe bash scripts or CI/CD pipeline configs (like GitHub Actions workflow files to build and deploy each part).
    
- **Documentation files:** Updated `README.md`, and possibly `docs/deployment.md` with details.
    

**File Structure & Key Files (Deployment):**

At the end of this phase, aside from the code, you have deployment-related artifacts in your project root:

- `Dockerfile` (multiple) – Each defines how to containerize a part of the app:
    
    - **`frontend/Dockerfile`**: instructions to build Next.js and serve it (using Next’s built-in server or exporting static and using a simple web server).
        
    - **`backend/Dockerfile`**: instructions to build and run Nest.js (compile TS to JS and run).
        
    - **`services/crawler/Dockerfile`**: instructions to set up the Python environment and run the crawler (this might simply run and exit if it's a one-shot, or could run a loop/schedule).
        
    - **`services/ai_matching/Dockerfile`**: instructions to run the AI Flask app continuously.
        
- `docker-compose.yml` – Defines a multi-container setup:
    
    - Services: `frontend`, `backend`, `crawler`, `ai_matching`, `db` (Postgres).
        
    - Specifies how they link (e.g., backend depends_on db and maybe ai_matching, etc., and environment variables for each).
        
    - Maps ports: e.g., `frontend:80->3000` (so front-end is accessible on port 80 of host), `backend:3001->3001`, etc., and `db:5432->5432`.
        
- **Infrastructure config (if any):** For example, if using AWS, maybe a Terraform file or AWS CLI setup (likely not needed for a prototype, so skip unless you are automating cloud setup).
    
- **Final Documentation:**
    
    - `README.md`: Now contains comprehensive info on setup, run, and usage. Likely sections for each component and how to deploy.
        
    - `docs/architecture.md`: Updated if needed to reflect the final deployed architecture (maybe including how services are hosted).
        
    - `docs/future_work.md`: (Optional) notes on potential improvements discovered during the project for later.
        

The deployment phase ensures the project is **accessible and running in a realistic setting**. By containerizing and documenting, you also make it easier to maintain or share. The result is a working web prototype, deployed and ready to demonstrate to users or stakeholders. All modules are in place (frontend, backend, crawler, AI service), aligned with the modular architecture principles we began with. The system is organized, scalable, and each piece can be worked on independently — a successful outcome for a solo-developed project with multiple technologies.