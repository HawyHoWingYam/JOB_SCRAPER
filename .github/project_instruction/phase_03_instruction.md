## Phase 3: Admin Dashboard and Role Management (RBAC)

**Objective & Direction:** Introduce an administrative interface and controls so that an admin user can manage the platform data (jobs, users, etc.). This phase will also solidify the role-based access control (RBAC) mechanism in the system, ensuring that regular users and admins have appropriate permissions. The admin dashboard is typically a separate front-end (or at least a separate section of the app) where an admin can view all users, jobs, and make modifications (edit or delete as needed). The focus is on enabling internal management of the platform's data through a GUI, and protecting those endpoints from unauthorized access.

**Detailed Tasks:**

- **Define Roles:** Update the user model to include roles more explicitly if not already. We have 'user' as default; now add an 'admin' role. In code, this can be an enum `Role { User = 'user', Admin = 'admin' }`. In the database, the `users` table can have a column `role` (text or enum type) which is 'user' or 'admin'. Mark at least one user as admin (either via a migration seed or by manually updating the DB for testing).
    
- **RBAC Guards in Backend:** Implement role-based access control in Nest.js:
    
    - Create a custom decorator `@Roles(...roles)` and a Guard to check for those roles (NestJS docs provide patterns for this). Essentially, use a `CanActivate` guard that reads `req.user` (populated by JWT AuthGuard) and allows access if the user’s role is in the allowed roles for that route.
        
    - Apply this guard to admin routes. For example, any route in an AdminController or any sensitive operation (like deleting a job posting) should require an 'admin' role. You can set the guard globally on certain controllers or use it as needed on specific endpoints.
        
    - Ensure that the JWT payload includes the user's role so the guard can check it. Modify your JWT signing in AuthService to include `role` in the token claims.
        
- **Admin Front-end Setup:** Create a new Next.js application for the admin dashboard (if following the multi-frontend monorepo approach), or incorporate admin pages into the existing front-end under an `/admin` path. A separate app (`apps/admin`) keeps it clean (admins will access via a different URL/subdomain perhaps). For this prototype:
    
    - Scaffold `apps/admin` via `create-next-app` (or simply copy the structure of `apps/frontend`). Configure it to also call the same backend API.
        
    - Implement a login page for admin (though you could reuse the same /auth endpoints; an admin can log in through the normal API but then use the admin UI).
        
    - Plan admin sections: **User Management**, **Job Management**, and possibly an overview dashboard.
        
- **Admin Dashboard Pages:**
    
    - **User Management:** Page `/admin/users/index.tsx` that lists all users. Use the backend to fetch all users (e.g., `GET /users` for admin). Only admins should be allowed to hit this endpoint, so guard it in backend (e.g., `@Roles('admin')` on UsersController.findAll). Display a table of users with columns like ID, email, role, registration date. Optionally, allow admin to edit a user:
        
        - Provide an edit form or inline controls to change a user's role (for example, promote a user to admin or vice versa).
            
        - Backend: implement `PUT /users/:id` to update user data (only admin can do this). This might live in UsersController or a dedicated AdminController.
            
        - Also consider if admin needs to delete a user (maybe not for MVP, but you could allow admin to remove a problematic user).
            
    - **Job Management:** Page `/admin/jobs/index.tsx` listing all job postings in the system. Fetch via `GET /jobs` but ensure this returns all jobs (including ones an admin might have hidden or those not approved by admin if any workflow like that exists in Phase 5). Possibly create a dedicated admin endpoint if needed. Show a table with job title, company, etc., and allow admin to:
        
        - Delete a job post (maybe if it's inappropriate or duplicate). Implement `DELETE /jobs/:id` in backend with admin guard to remove a job from DB.
            
        - Edit a job post. Perhaps an admin wants to correct a typo or update info:
            
            - Create `/admin/jobs/[id].tsx` which fetches job details and has a form to edit fields (title, description, etc.).
                
            - Backend: implement `PUT /jobs/:id` to update a job. Guard it for admin. The JobsService can have an `update(id, updateDto)` method for this.
                
        - If you have a concept of approving jobs (for those added by crawler or later by employers), an admin can toggle an 'approved' field. (This will be more relevant in Phase 5 when integrating crawled data.)
            
        - For now, assume admin can fully CRUD jobs.
            
    - **Dashboard Home:** Page `/admin/index.tsx` could show summary stats (like total users, total jobs, maybe number of resumes uploaded). This is optional but gives a nice overview. To get these, you might add endpoints or reuse existing (like count of users from /users, etc.). Keep it simple, maybe just static text or minimal counts by making a couple of API calls.
        
- **Integrate Admin Front-end with Backend:** Ensure the admin app can authenticate and communicate with the back-end:
    
    - Admins can use the same login API. Once logged in (with a token stored), the admin app attaches the token to requests just like the user app does.
        
    - If the admin app is served on a different origin (e.g., localhost:3002), enable CORS on the Nest API for that origin as well.
        
    - Protect the admin app routes on the client side too: e.g., if an admin is not logged in, redirect from admin pages to admin login. But rely on backend for true security.
        
- **Testing Admin Functions:**
    
    - Mark yourself as admin in the DB (or have a special login for admin).
        
    - Log into the admin UI with admin credentials.
        
    - Verify you can see the user list. Try changing a user's role and verify in the DB it updated.
        
    - Verify you can see the job list. Test deleting a job (check DB or the main site to see it disappear). Test editing a job and see the changes reflect on the main site.
        
    - Test that a normal user (with a user JWT) cannot perform admin actions (e.g., call the delete job API – should get 403 Forbidden due to the guard).
        
    - Also ensure that if a non-admin somehow loads the admin frontend (by knowing the URL), they can't do anything useful (their requests will be forbidden; you can also add a simple check on admin frontend to redirect if `user.role !== 'admin'` after login).
        
- **Admin UI/UX:** The admin interface can be utilitarian. It's for internal use, so it doesn't need to be fancy. However, ensure it's easy to navigate between sections (users/jobs). Possibly have a sidebar or menu on the admin pages linking to "Users", "Jobs", etc. If using a UI library, leverage ready components for tables and forms to speed up.
    
- **Unified vs Separate Apps:** Note that some projects choose to have one Next.js app and handle admin routes in it (with logic to show/hide based on role). That can reduce code duplication for shared components. However, it can also bloat the client bundle for normal users with admin code. Given our monorepo, having a separate admin app is fine for clarity. You can share code by factoring common components into a separate package if needed (not necessary in prototype).
    
- **Update Documentation:** Document how to use the admin interface, and how roles are assigned. For instance, note that by default no user is admin unless manually made so. In a real scenario, you might implement an invite or make the first registered user an admin (if it's your own use).
    

**Recommended File Structure:** (after Phase 3 additions)

```plaintext
project-root/
├── apps/
│   ├── frontend/ ...            # (User-facing app from Phase 2)
│   ├── admin/                   # New Admin Next.js application
│   │   ├── pages/
│   │   │   ├── index.tsx        # Admin dashboard home (stats or welcome)
│   │   │   ├── jobs/
│   │   │   │   ├── index.tsx    # List all jobs with admin actions
│   │   │   │   ├── [id].tsx     # Edit job page (or view details with edit form)
│   │   │   │   └── new.tsx      # (Optional) Create new job form (admin can post jobs manually)
│   │   │   ├── users/
│   │   │   │   ├── index.tsx    # List all users
│   │   │   │   └── [id].tsx     # Edit user page (e.g., change role)
│   │   │   ├── auth/
│   │   │   │   └── login.tsx    # Admin login page (could reuse components from frontend auth)
│   │   │   └── ... (additional admin pages if needed)
│   │   ├── components/
│   │   │   ├── UserTable.tsx    # Component to display users in a table
│   │   │   ├── JobTable.tsx     # Component to display jobs in a table
│   │   │   ├── UserEditForm.tsx # Form for editing user (change role)
│   │   │   └── JobEditForm.tsx  # Form for editing job details
│   │   └── utils/               # e.g., same api util for making requests
│   └── backend/
│       ├── src/
│       │   ├── modules/ ...     # (Jobs, Users, Auth, Resumes from before)
│       │   ├── common/
│       │   │   ├── roles.decorator.ts # Define Roles decorator
│       │   │   ├── roles.guard.ts     # Guard to restrict by role
│       │   │   └── jwt-auth.guard.ts  # (If not created earlier, a guard to check JWT)
│       │   ├── controllers/
│       │   │   └── admin.controller.ts # (Optional) Dedicated controller for admin-only routes 
│       │   └── app.module.ts         # Ensure to apply APP_GUARD for JwtAuthGuard globally, etc.
│       └── ...
└── ...
```

_(The admin front-end might share some code with the main front-end for login logic or styles. Consider a `packages/shared-ui` in monorepo if needed to avoid repeating yourself. The back-end may either integrate admin routes into existing controllers with guards or have separate controllers. Above is one way to structure it.)_

**Key File Responsibilities:**

- **roles.decorator.ts & roles.guard.ts:** These implement the RBAC mechanism in NestJS. The `Roles` decorator uses `Reflector` to set metadata on routes indicating required roles. The `RolesGuard` implements `CanActivate` to check if `request.user.role` is in the required roles for that route. You will bind this RolesGuard at the controller or method level for admin routes. Additionally, ensure the global `JwtAuthGuard` (which checks JWT and sets `req.user`) is applied so that `req.user` exists for RolesGuard to inspect.
    
- **Admin Pages (Front-end):**
    
    - _admin/pages/users/index.tsx:_ Fetches all users (via GET `/users` with admin token) and displays them using `UserTable`. Each row might have an "Edit" button linking to `/admin/users/[id]`.
        
    - _admin/pages/users/[id].tsx:_ Fetches the specific user and shows a form (UserEditForm) to change their role or other info. On submit, calls the API (PUT `/users/:id`). After saving, maybe redirect back to user list or show a success message.
        
    - _admin/pages/jobs/index.tsx:_ Fetches all jobs (GET `/jobs` with admin token — the backend can decide if this returns all including those not visible to regular users). Uses `JobTable` to display. Could have a "Delete" button on each row (with a confirmation step) that calls DELETE `/jobs/:id`, and on success, removes that row from state. Also an "Edit" button linking to `/admin/jobs/[id]`.
        
    - _admin/pages/jobs/[id].tsx:_ Fetch job, show JobEditForm to edit fields. Submit calls PUT `/jobs/:id`. After update, maybe redirect to job list or simply notify.
        
    - _admin/pages/jobs/new.tsx:_ If admin wants to create a new job entry manually (maybe to seed the system or test, or if acting as an employer), this page shows an empty JobEditForm and on submit calls POST `/jobs`. The backend should allow admin to create jobs (could be same endpoint used by employers later, but guarded appropriately).
        
    - _admin/pages/auth/login.tsx:_ Admin login form. In many cases, the regular login can be used by admin, but to keep the apps separate, you might implement it again or import the component from the main app if sharing code. Once logged in (and token stored), redirect to `/admin` home.
        
- **Admin Components:**
    
    - _UserTable.tsx:_ Likely uses an HTML table to list users. Could allow sorting by clicking headers if desired. Each row might include user ID, email, role, and action buttons.
        
    - _JobTable.tsx:_ Similar concept for jobs. Display key fields. If jobs have a long description, you might omit or truncate that in the table.
        
    - _UserEditForm.tsx:_ A form allowing admin to change a user's role (dropdown of ['user','admin']). Possibly allow changing email or name if needed. It will call the API on submit.
        
    - _JobEditForm.tsx:_ Fields for title, company, location, description, etc. This can be used for both editing and creating jobs (if you populate it with existing data or leave blank).
        
    - _Nav components:_ The admin app likely needs a navigation bar or sidebar. E.g., a simple header with links to "Users" and "Jobs" pages. Possibly a logout button that clears the token.
        
- **Back-end (Admin related changes):**
    
    - You may not need a separate AdminController if you use guards on existing controllers:
        
        - For example, in `UsersController`, add a method `@Get() @Roles('admin') findAll()` to list users (visible only to admin).
            
        - In `UsersController`, add `@Patch('/:id') @Roles('admin') updateUserRole(...)`.
            
        - In `JobsController`, ensure that create/update/delete methods are annotated with `@Roles('admin')` (since only admin can do those in this phase; later an employer role will also use create).
            
        - Alternatively, group some admin routes: `AdminController` could have `/admin/users` and `/admin/jobs` endpoints, but it's not strictly necessary. Using the roles guard might be enough to reuse the logic in UsersService/JobsService.
            
    - _UsersService/Controller:_ Add `findAll` method to return all users. Use this in the admin user list page. Also an `updateRole(id, newRole)` in UsersService, invoked by controller when admin updates a user.
        
    - _JobsService/Controller:_ Add `updateJob(id, dto)` and `remove(id)` methods for editing and deleting jobs. These should check if the job exists (handle not found) and then perform the action (for delete, perhaps a soft delete flag instead of actual removal, but for prototype actual delete is fine).
        
    - _Auth:_ If you want to prevent non-admin from accessing admin front-end, that's mostly a front-end routing concern. The back-end already prevents actions. You could also issue different JWTs or include role in token and let the admin app check it, but since admin app will only be used by admins, a simpler check after login "if user.role !== admin then logout" is fine.
        
- **Data handling:** Make sure that any data changes by admin reflect for normal users:
    
    - E.g., if admin deletes a job, that job should no longer appear on the main site job list (the GET /jobs for users likely filters out deleted ones or they're gone from DB).
        
    - If admin changes a user's role to admin, that person can now use the admin app (perhaps communicate to them out-of-band or via the DB).
        
- **Security:** Now that roles are implemented, double-check security:
    
    - All admin-only endpoints must be guarded. The roles guard should be tested.
        
    - Also ensure the JWT cannot be easily forged (use a strong secret in .env for signing).
        
    - Test that as a normal user you cannot, for example, delete a job by calling the API directly.
        
- **Seeding Admin:** If not already, create a mechanism to easily set a user as admin. You can have a SQL seed or a command-line script to update a user. It's useful in case you reset the DB and need to quickly get an admin account without manual SQL each time.
    

**Solo Development Tips:**

- _Leverage existing code:_ The admin app can reuse a lot of the front-end logic, just displaying it in a different way. To avoid duplicating API call logic, consider moving that to a common utility that both apps can import (since it's a monorepo, you can have a `utils` folder or even import from frontend to admin if configured). Same for types (e.g., a `Job` TypeScript type can be shared).
    
- _Focus on functionality, not design:_ The admin interface can be plain. Use basic HTML tables and forms initially; make sure the data operations work. You can refine styling later or as needed.
    
- _Validate admin actions:_ Since admin can make destructive changes (delete jobs, etc.), add confirmations in the UI (simple `window.confirm` on delete is fine) to prevent accidental clicks. Also, handle errors: if an admin tries to delete a job that was already deleted, the API might return 404; the UI should handle it gracefully (refresh list or show a message).
    
- _Time management:_ Building a whole admin app might sound heavy, but it's largely CRUD views. Scaffold the pages one by one. Start with the user list (small and straightforward), then job list, then editing capabilities. If short on time, you could skip editing and just allow deletion, or skip user editing (assuming roles won't change often). Do the critical parts that demonstrate control over data.
    
- _Testing across roles:_ Now you have to test as a normal user and as admin to ensure features segregate properly. It might help to have two browsers (or one incognito) — one logged in as user, one as admin — to see the differences. This will become more important in future phases (like when employers are introduced).
    
- _Keep admin secrets secure:_ If your admin app will be deployed, ensure it's not publicly indexable without login. Perhaps keep it behind a simple HTTP auth if needed during prototype stage. This might be overkill now, but note it for production (so random people can’t even see an admin login page).
    
- _Reflect on data model:_ With admin ability to manage data, you might realize needed fields or improvements (like an 'approved' flag for jobs). Jot these down as tasks for Phase 5 where data refinement happens. E.g., you might realize an admin needs to mark a job as "approved" rather than immediately publish it, which leads into the crawling scenario.
    
- _Use admin as a debugging tool:_ The admin UI essentially also serves as a debugging interface for you (the developer) to see what's in your database (like a lightweight CMS). So building it helps you visualize the data easily without directly querying the DB each time. This is a nice benefit as you add more complexity later.
    

**Module-Level Design Focus:** The introduction of admin and RBAC touches many parts of the system, so consider:

- **Authorization Architecture:** The project now has an authorization layer separate from the business logic. Keep this decoupled. The guards you implemented should remain simple (checking roles) and not contain business decisions. Business logic (like what data to return) can still reside in services but can use the user role if needed (for example, a JobsService might filter jobs by `approved=true` for normal users but return all for admin – you could implement that by passing the user's role or by having separate methods).
    
- **Extensibility for More Roles:** We know an "employer" role is coming (portal users). Design your RBAC in such a way that adding a new role is easy. For instance, the `Roles` decorator can take multiple roles (`@Roles('admin', 'employer')` to allow either). Make sure your code isn’t strictly assuming just two roles. Perhaps use constants or the enum for comparisons rather than string literals everywhere, to avoid typos.
    
- **Admin Module vs Existing Modules:** Decide if you want a distinct separation for admin logic. The current approach likely reuses UsersModule and JobsModule for admin functions (with guards). This is fine and reduces code duplication. Another way is to have an AdminModule that imports those modules and provides specialized controllers that still use the same services. Either is acceptable. For now, reusing existing modules with role checks is simplest.
    
- **Data Flow:** With admin in place, think about how data flows from creation to display:
    
    - E.g., if an admin creates a job via the admin UI, it calls the same `JobsService.create` that might be used by other processes (like crawler or employer portal later). Ensure that service sets default values properly (like a job created by admin could be automatically `approved` since admin did it).
        
    - Similarly, if admin changes a user role, how does that propagate? Immediately the user’s next JWT will include the new role if they log in again. You might want to invalidate existing tokens (not trivial without tracking, so probably skip for prototype). At least note that if you change a user to admin, they need to re-login to gain admin privileges in the token.
        
- **UI/Backend Contract:** Ensure your admin UI and API are in sync in terms of contract. For example, when updating a user, decide what the request body looks like (maybe `{ role: 'admin' }`) and ensure the backend expects that. Little mismatches can cause frustration.
    
- **Maintainability:** The codebase now has two front-end apps and one backend. Keep them organized. Possibly document how to run the admin app (if it's simply another `npm run dev` in that directory or a modification of root script to also start admin on a different port).
    
- **Testing Plan:** Consider writing basic tests for the role guard logic (e.g., a unit test for RolesGuard to ensure it denies/permits correctly). This is a crucial piece of security. Nest provides testing utilities to create a dummy `ExecutionContext` for guards. At least test it manually as done, but note to strengthen later.
    
- By the end of **Phase 3**, you have an admin who can manage content and a secure separation between admin and users. The system is now multi-tenant (admin vs normal user roles) which sets the stage for adding the AI features and more automation.
    
