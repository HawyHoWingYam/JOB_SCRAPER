## Phase 4: Back-End Development (Nest.js API Modules)

**Objective & Direction:** Implement the back-end logic in Nest.js by building out the planned modules and connecting to the database. This phase focuses on creating a robust, modular API that the front-end can rely on. The architecture will be **modular** – each feature or domain area gets its own Nest module, with controllers (for routing HTTP requests) and providers/services (for business logic and data access). Aim for a clean separation of concerns: authentication, job management, user profiles, etc., each handled in its own module. This will make the backend scalable and maintainable.

**Key Activities:**

- **Set Up Database Connection:** Install and configure the database integration. For example, if using TypeORM with PostgreSQL, install `@nestjs/typeorm` and `pg`. In `app.module.ts`, import the TypeORM module with the database connection settings (host, port, credentials, etc., likely loaded from environment variables). Alternatively, set up Prisma or another ORM if preferred. Ensure you have a running PostgreSQL database locally (or in Docker) for development.
    
- **Create Core Modules:** Generate Nest modules for each major feature domain:
    
    - **Auth Module:** Handles user authentication (login, registration). Create `auth.module.ts`, `auth.controller.ts`, and `auth.service.ts`. Implement endpoints for user signup and login. Use Nest’s Guards or Passport strategy for JWT or session-based auth (for prototype, simple JWT token authentication can be used).
        
    - **Users Module:** Manages user profiles and accounts. Files: `users.module.ts`, `users.controller.ts`, `users.service.ts`. Implement endpoints to get or update a user profile, perhaps different endpoints for different roles (e.g., an admin could get any user’s profile, a user can only get their own).
        
    - **Jobs Module:** Manages job postings and searches. Files: `jobs.module.ts`, `jobs.controller.ts`, `jobs.service.ts`. Implement endpoints for CRUD of job postings (create, read/list, update, delete jobs), and for job search (e.g., a GET endpoint that returns jobs filtered by keywords or category). Some endpoints may be public (job seekers searching jobs), while others require HR/admin role (posting or editing jobs).
        
    - **Applications Module:** (Optional in MVP) Handles job applications. If included, `applications.module.ts` with controller/service for when a job seeker applies to a job and for recruiters to view applications.
        
    - **Admin (Portal) Module:** You might not need a separate module if admin functionality is covered by Users/Jobs modules with admin privileges. However, you can create an `admin.controller.ts` under Users or a separate `admin.module.ts` to group admin-specific endpoints (like viewing system stats, managing any user, etc.).
        
- **Implement Services and Controllers:** For each module, write the service logic and controller routes:
    
    - In controllers, define RESTful endpoints (e.g., `POST /auth/login`, `POST /auth/register`, `GET /jobs`, `POST /jobs`, `GET /jobs/:id`, etc.). Use Nest’s decorators like `@Get`, `@Post`, `@Body`, `@Param` to handle request data.
        
    - In services, implement the business logic and database calls. For example, `JobsService` might have methods like `createJob`, `findJobs`, `applyToJob` etc., using a repository or ORM to interact with the `Jobs` table.
        
    - Ensure to enforce role-based access control (RBAC). You can use Nest guards to restrict routes by role, or simpler, check the user’s role inside controller methods. For instance, allow only admins or recruiters to create jobs, only job seekers to apply, etc.
        
- **Data Models and Entities:** Create data entity classes or schemas for each major data model if using an ORM. For example, a `User` entity (with fields id, name, email, role, etc.), `Job` entity (title, description, company, etc.), `Application` entity (linking User and Job), etc. These might reside in an `/entities/` directory or within each module folder if following a domain-driven structure.
    
- **Integrate Python Service Hooks:** Though the Python services will be built later, plan and implement how the backend will interact with them:
    
    - For the **crawler**: perhaps create an endpoint or a cron job in Nest to trigger the crawler (or simply expect the crawler to populate the database). For now, you might stub an endpoint like `POST /jobs/import` that the admin can call to indicate new external jobs should be fetched. This could later call the Python crawler (via a shell command or HTTP request to a running crawler service).
        
    - For the **AI matching**: perhaps create a service or provider in Nest that calls the AI service’s API. For example, `AiService` that makes an HTTP request to the AI matching service (to be built in Phase 7) to get match results. Stub this out (return dummy match data) so you can integrate it once the AI service is ready.
        
- **Testing During Development:** As you add each module and endpoint, do quick tests (using Postman or Nest’s e2e testing) to verify they work. For example, test that you can register a user, log in (and maybe get a token), create a job, list jobs, etc. This ensures your backend is solid before hooking up the front-end.
    
- **Update Documentation:** Document any API routes and data shapes. It might help to maintain an **API spec** document (or at least notes in `docs/` or README) so the front-end phase knows how to use the APIs. List endpoints, required request fields, and sample responses for reference.
    

**Types of Files to be Created:**

- **NestJS Module files:** One `.module.ts` file per module (Auth, Users, Jobs, etc.).
    
- **Controller files:** `.controller.ts` files for each module’s routes.
    
- **Service files:** `.service.ts` files implementing business logic for each module.
    
- **Data model/Entity files:** TypeScript classes or interfaces representing database tables (e.g., `user.entity.ts`, `job.entity.ts`). If using an ORM, these are entity definitions; if using a query builder, you might still create interfaces or DTOs.
    
- **DTO (Data Transfer Object) files:** Define shapes for request and response data (e.g., `create-job.dto.ts`, `update-user.dto.ts`) to enforce consistent data validation and typing.
    
- **Config files:** e.g., `ormconfig.json` or any Nest config modules usage, plus environment variable files (`.env`) updated with things like database URL, JWT secret, etc.
    
- **Utility classes:** e.g., guards for auth (`roles.guard.ts`), interceptors or filters (for logging or error handling) if needed.
    

**File Structure & Key Files (Backend after this phase):**

The backend `src/` directory will now contain multiple modules and supporting files. For example:

- **`backend/src/auth/`** – Authentication Module
    
    - `auth.module.ts`: Defines the Auth module and imports/exports necessary providers.
        
    - `auth.controller.ts`: Handles routes like login (`POST /auth/login`) and registration (`POST /auth/register`). It extracts user credentials from requests and uses AuthService.
        
    - `auth.service.ts`: Contains auth logic (verify user, hash passwords, generate JWT token, etc.).
        
    - `auth.dto.ts` (optional): Data Transfer Object for auth requests (e.g., LoginDto, RegisterDto).
        
- **`backend/src/users/`** – Users Module
    
    - `users.module.ts`: Defines the Users module.
        
    - `users.controller.ts`: Routes for user profiles (e.g., `GET /users/me`, `PUT /users/me`). Admins might have routes like `GET /users/:id`.
        
    - `users.service.ts`: Business logic for user accounts (fetching user data from DB, updating profiles).
        
    - `user.entity.ts`: Defines the User database model (fields, relations).
        
- **`backend/src/jobs/`** – Jobs Module
    
    - `jobs.module.ts`: Jobs module definition.
        
    - `jobs.controller.ts`: Routes for job postings and search (e.g., `GET /jobs`, `POST /jobs`, `GET /jobs/:id`). May also include endpoints like `GET /jobs/search?query=`.
        
    - `jobs.service.ts`: Logic for creating jobs, querying jobs (with filters or full-text search queries to DB), updating and deleting jobs.
        
    - `job.entity.ts`: Job entity defining how a job posting is stored (title, description, company, etc.).
        
- **`backend/src/applications/`** – Applications Module (if implemented)
    
    - `applications.module.ts`, `applications.controller.ts`, `applications.service.ts` for handling job applications (e.g., `POST /applications` when a user applies to a job, `GET /applications?jobId=` for recruiters to see applicants).
        
    - `application.entity.ts`: Defines Application model (relation between User and Job, plus status).
        
- **`backend/src/common/`** – (Folder for shared utilities across modules)
    
    - `guards/roles.guard.ts`: Checks user role for protected routes (for RBAC enforcement).
        
    - `decorators/current-user.decorator.ts`: Custom decorator to extract logged-in user info from request (if using JWT strategy).
        
    - `filters/http-exception.filter.ts`: (Optional) to format error responses consistently.
        
- **`backend/src/main.ts`** – Application entry (already existed, but might be updated to use validation pipes, etc.). For example, enabling `ValidationPipe` globaly to auto-validate DTOs, and setting up global prefix for API (like `/api`).
    
- **`backend/src/app.module.ts`** – Root module updated to import all the new feature modules (AuthModule, UsersModule, JobsModule, etc.) so that Nest can assemble the application. It might also import modules like TypeORMModule.forRoot (with DB config).
    
- **`backend/.env`** – Contains environment variables like `DATABASE_URL`, `JWT_SECRET`, etc. (Ensure not to commit secrets to version control; use a `.env.example` to document needed vars).
    

Each of these files has a clear purpose: **Controllers** handle HTTP requests and responses for a module, **Services** encapsulate the logic and interact with the **database** (via Entities/ORM), and **Modules** organize the structure, making the app modular. NestJS’s modular structure “encapsulates a closely related set of capabilities”, which keeps the codebase organized as it grows. By the end of this phase, the backend should be a working API with all necessary endpoints, albeit without the Python-powered features fully plugged in yet.
