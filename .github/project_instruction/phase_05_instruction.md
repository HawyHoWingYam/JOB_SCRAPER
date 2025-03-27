## Phase 5: Front-End Development (Next.js UI Implementation)

**Objective & Direction:** Build the front-end user interface using Next.js and TypeScript, implementing the pages and components for each part of the application. The front-end will consume the Nest.js API created in Phase 4 and present the data in a user-friendly way. Emphasize a **modular UI architecture**: create reusable components and organize the project so it remains maintainable as it scales. Since the project may have distinct interfaces for job seekers, recruiters, and admins, ensure the design can either handle conditional rendering based on user role or split into separate apps if chosen.

**Key Activities:**

- **Set Up Routing and Pages:** Using Next.js file-based routing, create pages for all major views:
    
    - For job seekers (client interface): pages like Home/Job Listings (to browse jobs), Job Details page (to view a specific job and an “Apply” option), Profile page (to view/edit their profile, upload resume), Login/Register pages, etc.
        
    - For recruiters/HR (portal interface): pages like Candidate Search (to search the resume database), Job Management (to post new jobs or view applicants for their jobs), etc.
        
    - For admin (admin interface): pages like Dashboard (to view statistics), Manage Users, Manage Jobs (approve or remove listings), and maybe controls for running the crawler or viewing match results.
        
    - If using one Next.js app for all, organize routes with prefixes or folders (e.g., `/portal/...` for recruiter pages, `/admin/...` for admin pages). If using separate apps, each app will have its own pages directory for its domain.
        
- **Implement Navigation and Layout:** Create common layout components such as a navigation bar and footer. For example, a top navbar that shows different menu items depending on the user’s role (or a separate navbar component per interface). Implement a consistent design (possibly using a UI library like Chakra UI, Material UI, or Bootstrap to speed up styling, or simple custom CSS modules).
    
- **Build Reusable Components:** Identify pieces of UI used in multiple places and implement them as components:
    
    - Job listing card component (showing job title, company, location, etc.), used in job list pages.
        
    - Job search bar/filter component.
        
    - Resume upload form component.
        
    - User avatar/profile component for navbar or profile page.
        
    - Tables or lists for admin to display statistics or lists of users/jobs.
        
    - Modal dialogs for confirmations (like deleting a job posting).
        
- **State Management & Context:** Since this is a small-to-medium app, Next.js with React Hooks may be sufficient for state. Use React Context or small state libraries if needed:
    
    - Auth context to hold the logged-in user state (and JWT token) globally, so different pages/components can know if user is logged in and their role. This context will also provide functions to log in, log out (making API calls to Nest backend).
        
    - Possibly use SWR or React Query for data fetching to handle caching of API responses (for performance and convenience when managing server state).
        
- **Integrate API Calls:** For each page or action, call the corresponding backend API endpoint:
    
    - Use `fetch` or Axios in `getServerSideProps` or inside `useEffect` hooks (for client-side rendering parts) to retrieve data from Nest.js. For example, on the Jobs List page, call GET `/jobs` API to fetch jobs; on the Job Detail page, call GET `/jobs/{id}`.
        
    - For form submissions (like login or apply to job), call the appropriate POST endpoints (e.g., POST `/auth/login`, POST `/applications`).
        
    - Handle loading states and error states in the UI (show spinners while waiting, show error messages if API returns an error).
        
    - Ensure to include authentication tokens in API calls when required (e.g., include the JWT in an Authorization header for protected endpoints like posting a job). Next.js can store the token in a cookie or memory via context.
        
- **Client-Side Validation & UX:** Add client-side validation for forms (like check required fields before sending to API) to complement the server-side validation. Ensure the UI is responsive (Next.js setup is mobile-friendly by default; add CSS as needed for different screen sizes).
    
- **Testing the Frontend:** Manually test the pages in a browser as you develop:
    
    - Create a test user by calling your API (you could temporarily allow registration via a page or use a seed script) and log in to verify protected pages.
        
    - Navigate through all flows: a job seeker browsing and applying, a recruiter logging in and viewing candidates, etc. (Some parts might not fully work until Phase 6/7 when Python services data is available; you can stub data for now).
        
    - Fix any issues with data display or API integration as they come up.
        
- **Refine Based on Backend:** It’s common to adjust either frontend or backend when integrating. If an API needs slight changes (e.g., include extra data in a response to avoid an extra call), you can tweak the Nest backend now as well. This iterative integration ensures the front-end and back-end mesh well.
    
- **Update Documentation:** Write usage notes or update the README on how to run the frontend and backend together, and maybe document any assumptions or required environment variables (like API base URLs). Also possibly maintain an **API reference** in docs for front-end developers (in this case, yourself) – listing endpoints and expected inputs/outputs, which helps ensure front-end correctly consumes the API.
    

**Types of Files to be Created:**

- **Next.js Page files:** `.tsx` files under `pages/` (or `app/` if using Next 13+) corresponding to each route/view (e.g., `jobs/index.tsx`, `jobs/[id].tsx`, `profile.tsx`, `login.tsx`, etc.).
    
- **React Component files:** Reusable UI components in a `components/` directory (e.g., `JobCard.tsx`, `Navbar.tsx`, `LoginForm.tsx`, etc.).
    
- **CSS/Style files:** CSS modules or global CSS for styling components (if not fully using a component library’s styles). Could be in a `styles/` folder or alongside components (e.g., `JobCard.module.css`).
    
- **Utility/helper files:** e.g., an `api.ts` or `fetcher.ts` to centralize API calls, context providers (like `AuthContext.tsx` for authentication state), and custom hooks (e.g., `useAuth()`).
    
- **Config files:** Possibly Next.js environment config like `.env.local` for front-end (to store base API URL or other config), and adjustments in `next.config.js` if needed (for example, enabling images from certain domains or other build settings).
    
- **Testing files:** If doing component tests or integration tests on front-end, you might have files like `__tests__/` or use Cypress for end-to-end tests (this might come in Phase 8, but you can start stubbing tests here if desired).
    

**File Structure & Key Files (Frontend after this phase):**

The frontend project will now have a more fleshed-out structure. For example, if combining all roles in one Next.js app:

- **`frontend/pages/`** – Contains Next.js page components for each route:
    
    - `index.tsx`: Homepage (perhaps a landing page or redirect to jobs list).
        
    - `jobs/index.tsx`: Jobs list page, showing available jobs with search filters.
        
    - `jobs/[id].tsx`: Job detail page for a specific job (uses dynamic route `[id]`).
        
    - `login.tsx` / `register.tsx`: Authentication pages for sign-in and sign-up forms.
        
    - `profile.tsx`: User profile page (job seeker’s own profile).
        
    - `applications.tsx`: (If job seeker can view their applications) A page to list jobs they applied to.
        
    - `portal/index.tsx`: Recruiter dashboard page (for HR portal home).
        
    - `portal/candidates.tsx`: Recruiter page to search/view job seeker profiles or applications.
        
    - `admin/index.tsx`: Admin dashboard page (summary of stats).
        
    - `admin/users.tsx`: Admin page to manage users.
        
    - `admin/jobs.tsx`: Admin page to manage all job postings.  
        _(Routes and file naming may vary – this is one way to structure by folders for role segments.)_
        
- **`frontend/components/`** – Reusable components and possibly sub-folders by feature:
    
    - `Navbar.tsx`: Top navigation bar component (displays links appropriate to the logged-in user’s role, or generic links if not logged in).
        
    - `Footer.tsx`: Footer component for the site.
        
    - `JobCard.tsx`: Component to display a job summary (used in jobs list).
        
    - `JobSearchBar.tsx`: Component for the search/filter form on the jobs page.
        
    - `ProfileForm.tsx`: Form for updating user profile info.
        
    - `ResumeUpload.tsx`: Component to handle file upload for resumes.
        
    - (Potential subfolders like `components/admin/`, `components/portal/` if you want to group components specific to those interfaces.)
        
- **`frontend/context/`** – Application state contexts (if used):
    
    - `AuthContext.tsx`: React Context provider for authentication state (holds current user info and token, provides login/logout functions to components).
        
- **`frontend/utils/`** – Utility functions and helpers:
    
    - `api.ts`: Functions for calling backend API endpoints (could wrap fetch calls, handle base URL and headers in one place).
        
    - `useRequireAuth.tsx`: A custom React Hook that redirects to login if user is not authenticated (to protect certain pages).
        
- **`frontend/styles/`** – Styling:
    
    - `globals.css`: Global styles (if any) applied to the app.
        
    - `JobCard.module.css`: Example CSS module for the `JobCard` component (if using CSS modules for component-scoped styles).
        
- **Key configuration files:**
    
    - `frontend/next.config.js`: Next.js configuration (might remain default for this prototype, unless you need to set up custom headers or environment variables here).
        
    - `frontend/.env.local`: Frontend environment variables (e.g., `NEXT_PUBLIC_API_URL` pointing to the backend API base URL).
        

Each of these files serves a clear purpose in the front-end: **Pages** correspond to the actual routes a user can navigate to, **components** are building blocks used by those pages, **contexts/hooks** manage cross-cutting concerns like auth state, and **utils** help with common tasks (like API calls). The architecture is designed to be modular: for example, if a new feature or section is needed, you add a new page and some components without tangling with unrelated parts. Next.js is unopinionated about structure, so we impose our own logical grouping to keep the code organized. This way, the front-end remains scalable as the app grows (it won’t turn into a jumble of files).
