
The following phase is optional, focusing on the employer portal if needed.

## Phase 6: Employer Portal & Candidate Management (Future Enhancement)

**Objective & Direction:** In this optional phase, extend the platform to support employer (recruiter) users, turning the prototype into a two-sided job marketplace. This involves building a portal front-end for employers to post jobs and review candidates, and integrating the application system from the job seeker's side (so job seekers can apply to jobs and employers can view those applications). The AI matching can also be leveraged here to help employers find suitable candidates (e.g., showing them recommended resumes for their job opening). This phase is about expanding user roles and interactions rather than introducing new technology components.

**Detailed Tasks:**

- **Employer Role and Authentication:** Introduce an 'employer' role in addition to 'user' and 'admin'. Possibly also a concept of Company if multiple users can belong to one company, but for simplicity, treat each employer user as a standalone or have a company field in their profile.
    
    - Update `Role` enum (if used) to include Employer.
        
    - Decide registration: you might not allow open employer registration (could invite or have admin create). For prototype, perhaps admin can designate a user as employer (set role).
        
    - Ensure the Auth system can handle a third role (mostly your guards just need to allow 'admin' or 'employer' where appropriate).
        
- **Portal Front-end:** `apps/portal` (if not created, do `create-next-app` for it). This portal will have pages for:
    
    - **Job Management:** List of jobs that this employer has posted. (This means filtering jobs by posted_by = current user). Page `/portal/jobs/index.tsx`.
        
    - **Post a Job:** Form to create a new job posting. `/portal/jobs/new.tsx`.
        
    - **Edit Job:** Perhaps allow editing their own job. `/portal/jobs/[id].tsx` for editing.
        
    - **View Applications:** For a specific job, list applicants (users who applied). `/portal/jobs/[id]/applications.tsx` or similar.
        
    - **Browse Candidates (optional):** Maybe a page to search all resumes by skill or see recommended resumes. `/portal/candidates.tsx`.
        
    - A dashboard home `/portal/index.tsx` showing an overview (e.g., how many active jobs, how many applications received recently).
        
    - A login page (or reuse main login – you could even have them log in via main site and redirect if role=employer).
        
    - Navigation for portal (links to Jobs, maybe to a profile or company info).
        
- **Back-end for Employer Actions:** Leverage existing modules:
    
    - **JobsController:** Allow 'employer' role to create jobs as well. You might do `@Roles('admin','employer')` on `POST /jobs`. In the JobsService.create, if `req.user.role == 'employer'`, set the `posted_by` to that user and perhaps set `approved=false` or true depending on trust. Possibly auto-approve employer jobs if you trust them, or send to admin for approval just like scraped ones.
        
    - For editing and deleting jobs: allow if the user is the one who posted it. This can be done by checking in JobsService or via a custom guard that checks `job.posted_by == currentUser`.
        
    - One approach: In JobsService, for update/delete, fetch the job, if currentUser.role is employer and job.posted_by != currentUser.id, throw Forbidden. If currentUser.role is admin, allow all. This logic can be incorporated as needed.
        
    - **ApplicationsController:** Already, as a user, applying to a job would create an Application entry. Ensure that route exists (e.g., `POST /jobs/:id/apply` which creates an application with user= currentUser, job= :id, resume = currentUser.resume). This should be allowed only for role 'user' or maybe also 'admin' if they want to simulate, but primarily 'user'.
        
    - Add `@Roles('user')` to the apply route (or just require auth and in service ensure non-employer perhaps).
        
    - **Viewing Applications:** For employers to view applicants:
        
        - Create `GET /jobs/:id/applications` in ApplicationsController. Use guard: allow 'admin' or 'employer' (who owns the job).
            
        - In service, ensure if role is employer, that job.posted_by = currentUser.id before fetching applications.
            
        - This returns list of applications, possibly including user info and resume summary. You might join User and maybe a snippet of resume or at least resume file link.
            
        - Alternatively, return application IDs and have the portal call a separate endpoint to get applicant details.
            
        - Simpler: embed basic info in the response: user name/email, and maybe a match score between that resume and the job (you can compute or retrieve from matches table).
            
    - **Recommended Candidates:** Use the matching data in reverse:
        
        - You have `match` scores for each resume-job. To suggest candidates for a job, query `match` table for job_id = X, get top resumes. Or simply query resume_skills vs job_skills overlaps similarly.
            
        - Provide `GET /jobs/:id/recommended-candidates` (admin/employer access). It could return a list of users (or resumes) sorted by match score who have not applied yet (to avoid duplicates with applicants).
            
        - This is advanced; you might skip in prototype or just conceptually mention it. Even showing "Match score" next to each applicant (like "This applicant is a 70% fit for the job") could be insightful for the employer.
            
    - Ensure resume privacy: presumably, when a user applies, they are willingly sharing their resume with that employer. But if you're suggesting candidates who haven't applied, you might need the user's consent or anonymize the info. For prototype, assume an open scenario or skip that feature.
        
- **Notifications (optional):** Possibly email or notify employers when new applications come in. You could have a placeholder function in ApplicationsService to send email (using nodemailer or similar) to the employer's email with applicant's name. Or simply count and show in UI.
    
- **Admin Oversight for Employers:** Admin should have some control over employer activities:
    
    - Admin may need to approve new job posts by employers (like we did for crawler). If trust is an issue, you can reuse the approved flag. Maybe default employer-posted jobs to approved=false and require admin to approve them (similar to crawler ones). Or if you trust them, auto-approve but allow admin to remove if needed.
        
    - Admin might also see the applications, but that's fine (they can view via admin if necessary to assist).
        
    - Possibly admin creates employer accounts or converts users to employer. If you want a UI: on admin user edit page, they can set role=employer.
        
- **Portal UI:**
    
    - _portal/jobs/index.tsx:_ Fetch jobs where posted_by = current employer (need an API: could reuse GET /jobs but filter server-side if role is employer to only return their jobs, or make a dedicated endpoint /my-jobs).
        
    - Display list, with counts of applicants for each (maybe an extra field returned by backend, or separate call to /jobs/:id/applications count).
        
    - Provide button "New Job", link to new job form.
        
    - Each job row could have an "Applications" link and maybe a "Close Job" if they want to mark position filled (could just delete or set a status).
        
    - _portal/jobs/new.tsx:_ Form to create job (title, description, etc.). On submit, calls POST /jobs. After creation, perhaps route to /portal/jobs (or /portal/jobs/[id] to view it).
        
    - _portal/jobs/[id].tsx:_ Show job details with an edit form or just info and edit button toggling fields. If you separate edit page vs view page it's fine; small app can just do one page for both view/edit.
        
    - _portal/jobs/[id]/applications.tsx:_ List of applications for that job. For each application, show applicant name, maybe email, and a link to view resume (you could link to an endpoint `/resumes/{resumeId}/download` or if resume text is stored, maybe show the text or a summary).
        
    - If you implemented match score for applicants: show "Fit: X%" if available (you can retrieve it by looking up in matches table for resume and job).
        
    - Possibly allow the employer to update application status here (e.g., mark as "Interview" or "Reject"). That could be a PATCH /applications/:id to update status.
        
    - _portal/candidates.tsx (optional):_ If recommending outside applicants, list some top candidates. If implemented, it would call `/jobs/{id}/recommended-candidates` or a global search by skill.
        
    - _portal/auth/login.tsx:_ Could be identical to admin login, or you can reuse the main site login. Maybe if an employer logs in via main site, you detect role and redirect to portal subdomain. For simplicity, have a separate login page that just posts to the same /auth/login endpoint.
        
    - Layout: ensure the portal pages have a navigation for "My Jobs", and perhaps "Profile" where they can edit company info or logout.
        
- **Email Integration (optional):** If time and needed, integrate an email service:
    
    - On job apply, send email to employer (if email known) with applicant info.
        
    - On job approval, maybe email employer that their job is published.
        
    - Use a service like SendGrid or just SMTP if available. But in a prototype, you can simulate or log emails to console.
        
- **Testing Multi-user flows:**
    
    - Create a user, mark them role=employer (via admin UI or directly in DB).
        
    - Log in as that employer on portal. Post a job. Check in DB that job exists with posted_by = employer's id, approved maybe false.
        
    - Log in as admin, approve that job if needed.
        
    - Log in as a regular user, see that job in listings. Apply to it.
        
    - Log back as employer, see the application in portal. Check resume link works (perhaps just having them view the resume info).
        
    - Test match suggestions: if implemented, ensure the scores make sense for each applicant.
        
    - Try edge cases: employer editing a job after posting (should update data), employer deleting a job (if you allow, make sure applications for it are handled or also removed).
        
    - Security: ensure one employer cannot edit or view another employer's job or applications by manipulating IDs. Your guard logic should prevent that (tested by trying to access a job id that isn't theirs).
        
    - Ensure admin can still do everything and sees all jobs (both crawler-posted and employer-posted). Possibly mark which jobs came from which source or who posted in admin view.
        

**Solo Development Tips:**

- _Reuse and adapt:_ The employer portal will reuse a lot from admin and main:
    
    - The job form can be similar to admin's job edit form.
        
    - The job list is similar to admin's, but filtered.
        
    - The application list is a new concept, but it's basically listing users similar to admin's user list but constrained by a job context.
        
    - So leverage existing components or at least copy-paste and adjust, to save time.
        
- _Role-based UI routing:_ Manage access: if an employer goes to main site pages, they could still see the job list etc., which is fine. But the portal is separate. Conversely, a normal user should not access portal pages (they wouldn't have link or permission). The backend guards anyway.
    
    - Possibly protect portal routes by checking if current user role is employer in a React useEffect and redirect to login if not.
        
- _Think of company context:_ If a recruiter posts multiple jobs or multiple recruiters from same company come, you might share jobs among them. That introduces complexity of organization accounts. For prototype, assume each employer user only posts their jobs. Or use one account per company.
    
    - If you did have a company model, you'd link jobs to company and users to company. That might be too much now, but keep in mind if expanding beyond prototype.
        
- _Keep employers in check:_ If you allow employer sign-up openly, someone could potentially see resumes without permission. Usually, platforms require a company verification. In prototype, maybe don't allow self-signup for employers to avoid that whole flow.
    
- _Polish user-apply flow:_ Make sure when a user applies, they know it succeeded. Perhaps on front-end, after clicking apply, show "Application submitted" and hide the button or disable repeat.
    
    - Ensure a user cannot apply twice (enforce uniqueness of user_id+job_id in applications table).
        
    - Possibly show on user's side a list of jobs they've applied to (Profile page "My Applications").
        
    - This can be a simple page listing those applications with statuses. This closes the loop for the job seeker, knowing which jobs they applied to and if any update.
        
- _Time management:_ If short on time, focus on job posting and viewing applications (the core of portal). The nice-to-haves like recommended candidates or application statuses can be outlined but not fully implemented.
    
- _Test thoroughly:_ Now you have three user roles to juggle. It's easy to introduce a bug where, say, an employer tries to view a job that isn't theirs and gets a generic error instead of a polite message. As a solo tester, simulate all roles:
    
    - user -> browse/apply
        
    - employer -> post/review
        
    - admin -> oversee
        
    - Ensure no obvious holes (like an employer being able to approve their own job even if intended only admin can, unless you allowed that explicitly).
        

**Module-Level Design Focus:**

- **Complete RBAC Implementation:** With all three roles active, verify your design covers all interactions:
    
    - Regular users: can search jobs, view jobs, upload resume, apply to jobs. They cannot edit or create jobs, cannot see others' resumes or applications (except their own).
        
    - Employers: can create/edit their jobs, view applicants for their jobs. They cannot view or edit jobs they didn't post, cannot see user list or resumes unless applied to their jobs or via recommendation feature explicitly allowed. They also cannot promote themselves or others to admin (no access to user management).
        
    - Admins: can do everything (manage jobs, users, skills, view all applications if needed).
        
    - Check that each API endpoint has proper guard conditions for these distinctions.
        
- **Data relationships final check:** Now the data model includes relationships:
    
    - A Job may be posted by an Employer (user_id) or by crawler (null user but has source).
        
    - A Job has many Applications; an Application links a User (job seeker) to a Job (and indirectly to the job's employer through the job).
        
    - A Resume is tied to a User; a User (job seeker) can have applications and a resume; a User (employer) can have jobs; an Admin is just a user with no special foreign keys.
        
    - Skills linked to both resumes and jobs.
        
    - Ensure no circular relations: It's mostly a star topology around user and jobs, which is fine.
        
    - Add foreign key constraints in DB to maintain integrity (like cascade delete an application's record if either the job or user is deleted).
        
- **Scalability & Partitioning:** If the system grows:
    
    - You might separate the job listings DB from user accounts DB (if it gets huge).
        
    - Or use ElasticSearch for searching jobs by criteria.
        
    - But at prototype, one database is fine.
        
    - The architecture now could be split into microservices: e.g., a "jobs service", "user service", "application service". But that adds complexity for a solo dev. Monolith is okay until it truly needs to scale.
        
- **Compliance and Privacy:** Now dealing with user resumes and employer data, consider:
    
    - Secure personal data: resumes may have personal info. Ensure only intended parties can view them.
        
    - Possibly implement a terms: e.g., user agrees that their resume will be shared with employers they apply to.
        
    - Not needed to code, but be mindful of it. E.g., don't let an employer access a resume unless the user applied.
        
    - This is partly enforced by design: applications table controls that.
        
- **Wrap-up:** At the end of **Phase 6**, the platform prototype supports:
    
    - Job seekers (find jobs, apply, get recommendations),
        
    - Employers (post jobs, see matching candidates and applicants),
        
    - Admin (oversee everything, maintain data quality).
        
    - It's a fully functioning small-scale job board with AI features, built in modular phases.
        
