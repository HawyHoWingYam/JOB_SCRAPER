
## Phase 5: Background Tasks, Data Pipeline & Advanced Refinements

**Objective & Direction:** In this phase, enhance the prototype with automation and data quality improvements. This includes setting up background processes for regularly fetching new job data (web crawler), refining how data is stored (raw vs cleaned data), automatically parsing resumes in detail, precomputing AI insights (rather than doing it synchronously in user requests), and standardizing data such as skills to improve match accuracy. Also, introduce workflows for admin or human-in-the-loop reviews where applicable (for example, reviewing automatically scraped data or AI-generated skill mappings). Essentially, Phase 5 transitions the project from a static MVP to a dynamic system that updates and maintains itself with minimal manual intervention, and improves the intelligence and reliability of the AI features.

**Detailed Tasks:**

- **Web Crawler Integration (Job Data Ingestion):** Use Python (Scrapy or similar) to build a crawler that fetches job listings from external sources. This will populate the platform with real job data automatically:
    
    - Create a Scrapy project in `services/crawler`. Choose a target source (for prototype, perhaps a known site with jobs in the public domain or a test RSS feed of jobs). For example, if you use **JobsDB** (as hinted in the Chinese overview), identify if it has an accessible feed or use HTML parsing.
        
    - Implement a spider (e.g., `JobsSpider`) that navigates the site and yields job items (title, company, location, description, etc.).
        
    - Use Scrapy's Item Pipeline to save data to PostgreSQL. For instance, define a pipeline that takes each scraped job item and inserts into a `raw_jobs` table. Alternatively, insert directly into the `jobs` table but initially mark them unapproved or not processed.
        
    - _Raw vs Cleaned:_ It's often wise to store raw scraped data first (so you have a record of exactly what was scraped). The `raw_jobs` table could have fields like source (e.g., 'JobsDB'), external_id (e.g., job ID or URL from source), raw_title, raw_description, etc., and maybe a processed flag.
        
    - Then have a process to transform raw data to your standard `jobs` table. This might involve cleaning HTML tags, trimming redundant info, or mapping fields (e.g., source might have separate fields for city, state, which you combine into location).
        
    - If the data source is reliable and matches your schema closely, you could skip raw and insert directly. But including raw data is helpful for auditing and avoiding duplicates.
        
    - Ensure you handle duplicates: e.g., if you run the crawler daily, it should not reinsert the same job over and over. Use the external_id or a combination of title+company as a key to check if it exists (Scrapy pipelines can drop items if already seen).
        
    - Set up Scrapy settings for database connection (you might reuse environment variables).
        
- **Scheduling the Crawler:** Decide how to run the crawler regularly:
    
    - If using a cloud environment, you might set up a cron job or a scheduled task. In development, you can trigger it manually.
        
    - Integrate with Nest: NestJS has a **ScheduleModule** (cron jobs). You could create a service in backend that runs at midnight and calls `scrapy crawl jobs_spider` via a shell command (similar to how you invoked the match script).
        
    - Alternatively, run the crawler as a separate process (outside the Node app) via OS scheduling (like a cron tab or a simple loop in a Python script that sleeps).
        
    - For MVP, perhaps execute it manually to simulate daily run, but ensure the code structure can accommodate periodic execution.
        
- **Processing Scraped Data:** If you used a raw_jobs table:
    
    - Implement a processing script (maybe as part of the crawler pipeline or a separate step in Nest or Python) to convert raw job data to final jobs.
        
    - This might involve:
        
        - Removing duplicates (if two sources have the same job, decide whether to keep one).
            
        - Standardizing formats (e.g., location "New York, NY" vs "NYC" – these could be normalized if needed).
            
        - Extracting skills from job description (for matching improvement). You could run a similar extraction as resumes: find key skills in job postings and store them (perhaps fill a `job_skills` join table linking job to skills).
            
        - Once a raw job is processed, insert or update the `jobs` table. Mark it as approved/published only after admin review (see next point).
            
        - Mark raw job as processed to avoid reprocessing next time.
            
    - You can implement processing in Python or inside the Nest backend. For example, a Nest CronJob could select all raw_jobs where processed=false, do transformations (maybe even call the AI skill extractor for the description), insert into jobs table, and set processed=true.
        
- **Skill Standardization (Taxonomy Integration):** To improve matching quality:
    
    - Create a `skills` table (if not already from Phase 4) that will hold unique skill names. Populate it with a predefined list of common skills if available (there are public lists like from O*NET for tech skills, or compile from your job data by extracting frequent words).
        
    - When parsing resumes and jobs for skills, instead of treating the skill as just text, map it to an entry in `skills` table.
        
        - For example, if resume extraction finds "Node.js" and "Node", map both to a single skill entry "Node.js". You might maintain a synonyms list or a simple normalization function (like lowercase and strip punctuation, maybe unify plural/singular).
            
        - If a skill is not in the table, either add it or map it to a closest existing skill (this could be a complex task; for MVP, maybe add all new as separate entries).
            
    - Update the matching calculation to use skill IDs (the overlap of sets of skill IDs ensures "Node" vs "Node.js" are treated as match if mapped to same id).
        
    - This likely requires populating join tables:
        
        - `resume_skills` (resume_id, skill_id)
            
        - `job_skills` (job_id, skill_id)
            
    - You can populate these when parsing: e.g., after extracting skills from a resume, for each skill string, find or create a skill entry, then insert a row in resume_skills.
        
    - Do similarly for job descriptions when processing them.
        
    - This structured approach not only improves matching but also gives you data to possibly do skill-based search or recommendations in the future.
        
- **Admin Review Workflows:**
    
    - **Job Approval:** If jobs are auto-imported, an admin might need to verify them (especially if scraping broad sites where content might not all be relevant). Introduce an `approved` flag in `jobs` table. The Jobs that come from crawler can default to `approved=false`.
        
    - Update the user-facing jobs listing to filter only approved jobs (e.g., JobsService.findAll for normal users adds `where approved=true`).
        
    - Provide an admin UI page (e.g., `/admin/jobs/pending`) showing unapproved jobs. Admin can then view details and click "Approve" or "Reject".
        
        - Approve sets `approved=true` (job becomes visible).
            
        - Reject could either delete it or mark it rejected (maybe keep it in DB but not show). If you keep it, ensure the crawler doesn't re-add it (mark the raw record or track its external_id in a blacklist table).
            
    - This ensures quality control. If your source is high quality, this might be less necessary, but it's a good feature to demonstrate.
        
    - **Skill Mapping Review:** If the automatic skill mapping isn't perfect, allow admin to merge or alias skills:
        
        - Admin page `/admin/skills` listing all skills in the system (from `skills` table). Show how many resumes and jobs have each skill (this can be a query that counts resume_skills and job_skills for each).
            
        - If you see duplicates like "node" and "node.js", admin can choose to merge them. Implement a function to merge skill A into skill B:
            
            - This means update all resume_skills and job_skills of A to B, then delete A or mark it as alias.
                
            - The admin UI can have a merge form: select skill A, select skill B, click merge.
                
            - Backend: have an endpoint `POST /skills/merge` with ids, that performs the updates in a transaction.
                
        - This is an advanced but valuable tool to continuously improve data quality. It’s a form of human-in-the-loop for AI, as the admin helps maintain the taxonomy.
            
        - Also consider preventing trivial differences: e.g., store skills in lowercase to avoid case duplicates.
            
    - **Monitoring AI Outputs:** Provide admin insight into the AI matching:
        
        - Perhaps a page to see if any resume had very low matches (which might prompt an admin or career coach to suggest the user improve their resume).
            
        - Or see if some jobs are getting no matches (maybe they require uncommon skills, indicating a supply/demand gap).
            
        - These are optional analytical views. At minimum, maybe log or show in admin dashboard something like "Average match score across all applications" or "Number of recommendations generated".
            
- **Precompute and Schedule AI tasks:**
    
    - Move the heavy AI computations off the user request cycle:
        
        - The crawler will add new jobs daily; you should then compute matches for those new jobs against all resumes (or vice versa). Doing this in real-time when the user logs in could be slow if data grows.
            
        - Set up a nightly job (via Nest Schedule or separate script) to refresh match scores:
            
            - For each resume in the system, compute match with new jobs (or all jobs, possibly overwriting previous scores).
                
            - Or for each new job, compute matches with all resumes and insert.
                
            - Decide which loop is smaller: if resumes are fewer than jobs, loop resumes and for each get matches. Or maintain incremental: e.g., keep track of last crawled job ID, and for new jobs do matches.
                
        - This can reuse the Python matching logic but running in batch. You might adapt `run_match.py` to run for all resumes or all jobs as needed.
            
        - Ensure not to duplicate entries in match table: you might clear out match table and recalc fully each time if simpler (assuming manageable size). Or delete only those for resumes that changed and jobs that are new.
            
    - **Resume Parsing Improvements:** If not done earlier, schedule resume parsing:
        
        - If some users upload resumes but you didn't extract skills or experience from them, you can do it in a batch (maybe immediately at upload as done, but also if you add new parsing logic, re-run on all existing resumes).
            
        - For example, if you later decide to extract "years of experience" from resume, you might update code and then want to apply it to all stored resumes. A background task can handle that.
            
    - Summarizing, by phase 5 end, ideally no intensive computation (crawling or matching) is happening during a user interaction — it's done offline and results are ready to be served quickly on request.
        
- **Performance and Scaling:** With these background tasks, think about concurrency and load:
    
    - If crawler runs at 3 AM and pulls 1000 jobs, and match runs at 4 AM for 100 resumes, ensure database can handle the inserts. Use transactions or bulk insert if possible to optimize.
        
    - If using Python for heavy loops, ensure it's efficient (maybe using vector operations or efficient data structures).
        
    - Memory: if very large data sets, be mindful not to load all jobs into memory at once in Python; you could stream or chunk processing.
        
    - But for prototype, these concerns are minor. It's more about demonstrating the mechanism.
        
- **Housekeeping:** Clean up or archive outdated data:
    
    - If a job expires (maybe the source removed it or it's older than X days), you might want to mark it inactive or remove it. The crawler could check if jobs from last run are still present this run, and if not, mark them expired. Alternatively, keep everything and let admin prune.
        
    - If a user uploads a new resume, you may want to either keep the old one for record or replace it. In design, maybe only latest is kept (so update resume record instead of adding a new one).
        
    - Over time, there could be many raw_jobs entries (if not deleting old ones). Maybe have a policy like "keep last 6 months of raw data".
        
    - These are more production concerns, but it's good to note them.
        

**Recommended File Structure:** (after Phase 5 additions and adjustments)

```plaintext
project-root/
├── apps/
│   └── backend/
│       ├── src/
│       │   ├── modules/
│       │   │   ├── jobs/
│       │   │   │   ├── job.entity.ts        # Add fields: source, externalId, approved, etc.
│       │   │   ├── skills/                 # New module for Skill taxonomy
│       │   │   │   ├── skills.module.ts
│       │   │   │   ├── skills.controller.ts# Admin endpoints for skills (list, merge)
│       │   │   │   ├── skills.service.ts   # Logic for finding/merging skills
│       │   │   │   └── skill.entity.ts     # Skill entity (id, name)
│       │   │   ├── resume_skill.entity.ts  # Join table entity linking resumes<->skills
│       │   │   ├── job_skill.entity.ts     # Join table entity linking jobs<->skills
│       │   │   ├── applications/           # (Optional module for job applications)
│       │   │   │   ├── applications.module.ts
│       │   │   │   ├── applications.controller.ts
│       │   │   │   ├── applications.service.ts
│       │   │   │   └── application.entity.ts # Application entity (id, job_id, user_id, status, applied_at)
│       │   ├── tasks/                      # Module or folder for scheduled tasks
│       │   │   ├── tasks.module.ts         # Import ScheduleModule and providers
│       │   │   └── crawler.tasks.ts        # Service with @Cron jobs to run crawler and matching
│       │   └── ...
│       └── ...
├── services/
│   ├── crawler/
│   │   ├── scrapy.cfg
│   │   └── jobcrawler/
│   │       ├── spiders/
│   │       │   └── jobs_spider.py          # Spider for scraping job listings
│   │       ├── pipelines.py               # Pipeline to save to DB
│   │       ├── items.py                   # Define JobItem with fields like title, company, etc.
│   │       └── settings.py                # Configure pipelines, DB connection
│   └── ai/
│       ├── ... (existing AI scripts from Phase 4, possibly enhanced)
│       ├── taxonomy/ (optional directory)
│       │   └── skills_taxonomy.json       # a JSON or data file listing known skills for reference
│       └── ... (no major changes here, maybe improved parsing logic)
└── ...
```

**Key New/Updated Components:**

- **job.entity.ts (updated):** Add fields:
    
    - `source` (varchar) – e.g., 'JobsDB' or 'Manual' or 'Employer'.
        
    - `externalId` (varchar) – unique id from source if available (for deduplication).
        
    - `approved` (boolean) – default false for imported jobs, true for admin-created or admin-approved jobs.
        
    - `posted_by` (nullable FK to User) – if later employers post jobs, this links the job to the employer account (to differentiate from crawler or admin entries).
        
    - Possibly `created_at` and `updated_at` timestamps if not already present.
        
- **skill.entity.ts (new):** Fields:
    
    - `id` (int PK),
        
    - `name` (text, unique).
        
    - You could also have a `normalized_name` or `alias_of` (self-referencing FK if this entry is an alias to another skill). But since we're merging by actually updating references, you may not need alias_of; merging physically consolidates entries.
        
- **resume_skill.entity.ts (new join table):** Links resume_id to skill_id. If using TypeORM, mark resume_id and skill_id as PKs (composite key). This table is filled whenever a resume is parsed for skills.
    
- **job_skill.entity.ts (new join table):** Links job_id to skill_id. Filled during job data processing (either from manual input by admin/employer or automated extraction from description).
    
- **applications.module (optional):** If implementing job applications:
    
    - _application.entity.ts:_ Fields: id, job_id, user_id, resume_id (maybe store the resume used to apply, though if one resume per user it's same as user_id), status (e.g., 'applied', 'reviewed', 'rejected', 'hired'), applied_at timestamp.
        
    - _applications.service.ts:_ Methods like `apply(userId, jobId)` to create an application, `findByJob(jobId)` to list applicants for a job, `findByUser(userId)` to list a user's applications.
        
    - _applications.controller.ts:_ Endpoints: `POST /jobs/:id/apply` (user applies to a job), `GET /jobs/:id/applications` (admin or employer views applicants). These would be used in Phase 6 likely.
        
- **skills.service.ts (new):** Functions:
    
    - `findOrCreate(name: string): Skill` – finds a skill by name (case-insensitive perhaps) or creates it if not exists.
        
    - `mergeSkills(sourceId, targetId)` – merges skill with id=sourceId into skill with id=targetId: update all references in resume_skill and job_skill from sourceId to targetId, then delete sourceId entry. Use within a transaction.
        
    - `listSkillsWithUsage()` – perhaps returns all skills with counts of resumes/jobs using them (SQL join+count).
        
- **skills.controller.ts (new):**
    
    - `GET /skills` – returns list of skills (possibly with usage counts) for the admin UI.
        
    - `POST /skills/merge` – expects JSON { from: skillId, to: skillId } and calls service to merge. Only admin can call this.
        
    - Apply `@Roles('admin')` on all routes, since only admin manages taxonomy.
        
- **crawler.tasks.ts (new Service for scheduling):** Use `@Cron` decorators:
    
    - e.g., `@Cron('0 0 * * *')` (midnight daily) on a method `runCrawler()` that executes the Scrapy spider. Could call `exec('scrapy runspider jobs_spider.py')` or use Python subprocess call similarly to how matching was done. Alternatively, integrate a python runner or have a REST endpoint in crawler (less typical).
        
    - `@Cron('30 0 * * *')` (12:30am) for `processRawJobs()` to process any newly scraped data.
        
    - `@Cron('0 1 * * *')` (1am) for `updateMatches()` to recalc matches after new jobs and possibly parse new resumes.
        
    - Cron expressions can be adjusted as needed. During development, you might trigger manually or set short intervals for testing.
        
- **pipelines.py (Scrapy):** In `process_item`, do something like:
    
    ```python
    # pseudo-code
    cur.execute("INSERT INTO raw_jobs (external_id, source, raw_title, raw_description, raw_location) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (source, external_id) DO NOTHING", ...)
    ```
    
    Use ON CONFLICT if using Postgres to avoid duplicates by unique (source, external_id). Or check existing first. Mark items with processed=false initially.
    
- **Admin UI additions:**
    
    - _admin/jobs/index.tsx:_ Add a filter or separate view for unapproved jobs. Maybe show them highlighted or have a tab "Pending Approval". For each pending job, provide Approve/Reject buttons.
        
    - Implement Approve by calling `PUT /jobs/{id}/approve` (create this endpoint or reuse update with a field) and updating the UI list (move it to approved section).
        
    - Implement Reject by calling `DELETE /jobs/{id}` or `PUT /jobs/{id}/reject` (depending on if you keep record). If keeping record, you might just delete it anyway for simplicity.
        
    - _admin/skills/index.tsx:_ New page listing skills from API. Show skill name and counts. Possibly allow sorting by name or count.
        
    - Next to each skill, maybe an input to rename or a way to select two skills to merge:
        
        - You might allow selecting a checkbox for two skills and then click "Merge Selected" (merging the first into the second). Or a dropdown on a skill row "Merge into..." that pops up a list of other skills.
            
    - Simpler: have an input where admin types the name of the skill to merge into and an action button.
        
    - _admin/skills_ actions will call the `/skills/merge` API.
        
    - This UI can be basic since used by admin only. Even an approach like requiring admin to use a script to merge is okay, but since asked for multi-phase guide, an interface is good to mention.
        
- **Portal considerations:** Although Phase 6 will flesh out employer portal, some groundwork in Phase 5 helps:
    
    - The `applications` table and module introduced is mainly for employer side. Admin can see them too, but it's more for connecting job seekers and jobs in a transactional way.
        
    - By implementing it now or at least planning it, you're ready to support the "Apply" feature. If time permits, you could allow job seekers to click "Apply" on a job (just record in DB, maybe send an email to admin or a placeholder since no employer UI yet).
        
    - Admin could see applications in admin panel (maybe under users or jobs).
        
    - This sets up for Phase 6 where employers will view these.
        
- **Testing End-to-End After Phase 5:**
    
    - Run the crawler (maybe manually trigger the cron or call the command). See that new jobs appear in admin pending list.
        
    - Approve a couple of scraped jobs. Check they show up on main site.
        
    - Upload resumes and see that matching still works with new jobs.
        
    - Try the skill merge: if you see redundant skills in admin skills list, use merge and then verify resume_skills and job_skills tables reflect the change (no references to old skill, all moved to target).
        
    - Test the scheduled match update by adding a new job (via crawler or admin) and see if the next match run picks it up for existing resumes (if you don't want to wait for actual cron, call the function manually or change cron to every minute for testing).
        
    - Ensure everything still works for normal flow: searching jobs (which now includes possibly many jobs), viewing details (make sure description formatting is okay if came with HTML or special chars; you might need to strip tags in processing).
        
    - Test performance on pages if you loaded lots of data (1000 jobs list should still load quickly if pagination or lazy loading might be needed in real scenario, but not now).
        
- **Documentation & Clean-up:**
    
    - Update your README/design doc to note that the system now has an automated data pipeline: "jobs are fetched daily from source X, admin must approve them in admin UI, then they become visible".
        
    - Note any config needed (like environment variables for crawler DB connection, or if any API keys for AI).
        
    - Clean code: remove debug prints or at least guard them. Make sure secrets (like DB password, API keys) are in config files, not hardcoded in code (especially in Python scripts).
        
    - Summarize how matching improved: e.g., "the matching now uses standardized skill mapping, so synonyms are handled better, improving recommendation relevance."
        

**Solo Development Tips:**

- _Phased rollout of features:_ Phase 5 is big, containing crawling, skill taxonomy, admin workflows, etc. Implement in sensible order:
    
    1. Skill system (because it can refine your matching immediately).
        
    2. Crawler (to get more data to test scaling).
        
    3. Admin approval of jobs (to manage crawler output).
        
    4. Applications (if doing, or skip if focusing on data side).
        
    5. Final schedule tasks to tie it together (once manual processes work, automate them).
        
- _Leverage community resources:_ Writing a Scrapy spider or dealing with job data might have been done by others. Look up Scrapy examples for PostgreSQL pipeline (like the one we found) and adapt. Also, if the site has an API, consider using that instead of scraping HTML (saves time).
    
- _Testing scrapes in isolation:_ Run the Scrapy spider alone (e.g., `scrapy crawl jobs_spider -o output.json`) to see if it collects data properly. Only then integrate DB pipeline to reduce debugging complexity.
    
- _Be mindful of scraping ethics:_ If you target a real site, do it politely: use a reasonable download delay, identify your bot with a user agent, and respect `robots.txt` unless you have permission. For prototype, one run is fine, but mention that continuous scraping should be mindful of not overloading sources.
    
- _Data cleaning focus:_ Garbage in, garbage out. Spend time on the cleaning step. If job descriptions have a lot of extraneous content (like company boilerplate), it could confuse matching. Perhaps trim job descriptions to the "Responsibilities" and "Requirements" sections if possible. If not, it's fine, just note possible future improvement.
    
- _Balance automation and control:_ Automating is great, but ensure you (as admin/dev) have control if something goes wrong. For example, log each time the crawler runs and how many jobs it added. If one day it adds 10,000 jobs which seem wrong, admin should catch that. Maybe send a summary email (could configure that later).
    
- _Quality vs quantity:_ It's better to have fewer high-quality job listings than thousands of spammy ones. If your source might include duplicates or irrelevant postings, incorporate filters (maybe by keyword or location to focus on a niche in prototype). E.g., only scrape jobs that contain "Engineer" or a certain location to keep data relevant.
    
- _Consider using a queue for tasks:_ If Nest's Schedule is too static, a more dynamic approach is using a queue (like Bull for Node) for tasks like matching each resume or sending emails. This might be too advanced to implement fully here, but keep the concept in mind. At least ensure that your scheduled tasks catch exceptions so one failure doesn't stop the next runs.
    
- _Final touches to matching:_ With standardized skills, maybe revisit your match scoring. If now both resumes and jobs have skill sets, the score formula might change slightly. Possibly give more weight to certain skills (if you parsed years, maybe weight skills by experience years, etc.). For now, still keep it simple, but ensure the refactoring to skill IDs didn't break logic.
    
- _User notifications:_ If new jobs are added daily, maybe email users or notify them. This is a feature beyond prototype scope, but you might note it. Similarly, if a great match job appears, notify the candidate. That’s a potential future enhancement.
    

**Module-Level Design Focus:** By now, the system has many moving parts. Reflect on the architecture:

- **Microservices vs Monolith:** You have essentially a monolithic repo with some microservice-like components (crawler, AI). Consider if in future you'd separate them. The design now keeps them loosely coupled (integration via DB or CLI calls). This is fine. If scaling, you might turn the crawler into a standalone service and the AI into another, communicating via message queues.
    
- **Data Consistency:** With multiple sources writing to DB (crawler, admin, AI scripts), ensure consistency:
    
    - Use transactions in merges and updates to avoid partial updates.
        
    - If two processes might update same data (unlikely here, but e.g., if admin approves a job at same time crawler tries to insert it, or two admin merging skills simultaneously), handle locking or constraints properly.
        
    - For example, the unique constraint on skills name prevents duplicates even if two processes try to add at same time.
        
- **Cross-module interactions:** Modules now interact: e.g., SkillsModule is used by ResumesModule (when parsing a resume, need to call SkillsService.findOrCreate). You might import SkillsModule into ResumesModule. Ensure to avoid circular imports (if any). Perhaps ResumesService can directly use SkillsRepository instead of full module import to reduce coupling.
    
- **Performance strategy:** The architecture should allow horizontal scaling if needed:
    
    - The crawler could run on a different machine or a lambda function.
        
    - The matching could be distributed (each resume match in parallel).
        
    - The database might become a bottleneck if too many writes at once; batching operations (like inserting match scores in one SQL COPY or transaction) can help.
        
    - Identify any potential slow point: e.g., loading all jobs in Python – can the DB handle that query efficiently? Add indexes on text if doing text search.
        
    - For now, fine, but highlighting such points means you're aware and can address them if this moves beyond prototype.
        
- **Completeness of features:** With Phase 5 done, check against requirements:
    
    - Job search ✅
        
    - Resume upload ✅
        
    - Admin dashboard (user/job management) ✅
        
    - Simplified AI matching ✅
        
    - Background tasks (crawler, etc.) ✅
        
    - Skill standardization ✅
        
    - Admin reviews (jobs approval, skill merging) ✅
        
    - The core workflows are solid and even some advanced ones are in place. The next phase will handle the employer side, which is an extension of the same patterns (role-based UI and permissions, using existing data structures like jobs and applications).
        

At this point, the prototype is not only functional but also smart and somewhat autonomous. The solo developer can maintain core workflows (with admin oversight) and the system can grow with new data daily.