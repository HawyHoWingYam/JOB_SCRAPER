## Phase 6: Development of Python Web Scraper Service (Crawler)

**Objective & Direction:** Create the Python-based **web scraping (crawler) service** that will periodically fetch job data from external sources (e.g., job board websites like JobsDB, as mentioned in the project instructions). The goal is to have an automated way to populate the platform’s database with job listings, which the Nest.js backend and Next.js front-end can then use. This phase is about implementing the crawler in a modular, maintainable way, separate from the main web app, but integrated into the overall system.

**Key Activities:**

- **Design the Crawler Functionality:** Decide on the target source(s) for job listings (for example, JobsDB or similar job sites). Identify how to navigate their HTML or API to retrieve job postings. Determine the fields to scrape (job title, company, location, salary, description, etc.).
    
- **Set Up the Python Project:** In the `/services/crawler/` directory, set up a Python module or use a framework like **Scrapy** for structured crawling. For a simpler start, you can use `requests` and `BeautifulSoup` to fetch and parse HTML. Install needed libraries (update `requirements.txt` with these).
    
- **Implement Crawling Script:** Write the Python code to perform the web scraping:
    
    - If using Scrapy: define a Spider class with parsing logic for the job listings page(s).
        
    - If using a simple script: fetch the page content, use BeautifulSoup (or similar) to parse out job details.
        
    - Handle pagination or multiple pages if the source has many listings.
        
    - Implement delays or obey robots.txt if applicable, to be polite to the source site.
        
- **Data Cleaning & Transformation:** Once raw job data is scraped, clean it up:
    
    - Normalize fields (e.g., consistent date formats, location formats).
        
    - Remove duplicates or very similar postings (deduplication). Initially, a simple check by job title + company might suffice; later you can implement more advanced similarity checks (e.g., TF-IDF + cosine similarity as per project notes, but that can be an enhancement).
        
    - Structure the data as per your database schema (i.e., ensure you have values for all required columns in the jobs table).
        
- **Database Insertion:** Connect the crawler to the database so it can save the scraped jobs:
    
    - You can use a Python DB library (like `psycopg2` or SQLAlchemy) to insert directly into PostgreSQL.
        
    - Alternatively, the crawler could output data to a JSON or CSV, which the Nest backend could consume via an API endpoint. However, direct DB insertion is straightforward for a prototype.
        
    - Ensure that the crawler marks records in a way that the system knows they are external (maybe a flag in the job record, or just treat them the same as any job).
        
    - If using an ORM on the Nest side, ensure consistency in how IDs are generated or how relationships are handled (for example, jobs inserted by crawler have no “poster user”).
        
- **Testing the Crawler:** Run the crawler script independently to verify it works:
    
    - Check it retrieves a sample of jobs correctly.
        
    - Verify those jobs appear in the database (e.g., connect to DB and SELECT from the jobs table to see the inserted entries).
        
    - Handle any errors (network issues, changes in source HTML) gracefully with try-except and logging.
        
- **Scheduling the Crawler:** Decide how this will run periodically. For a prototype, you can run it manually as needed. If you want automation:
    
    - Simplest: use a cron job on your system to run the Python script daily.
        
    - Alternatively, integrate with the Nest backend by exposing an endpoint that triggers the crawl (the Nest backend could call the Python script via shell or HTTP and then return). This way, an admin could click “Run Crawler” in the UI (admin-frontend) which calls Nest (which in turn calls the script). This might be more complex, so cron or manual run is fine for now.
        
- **Integrate with Backend:** Ensure the Nest.js backend is aware of the crawled data:
    
    - If the crawler writes directly to the DB, the backend’s job endpoints should automatically start showing those jobs (since they query the DB). You might want to add a field like `source` (internal vs external) in the Job entity to differentiate if needed for display.
        
    - If the crawler uses an API approach, implement a Nest endpoint to receive new job data (e.g., POST `/jobs/import` that accepts a batch of jobs and inserts them). Then modify the crawler to send HTTP requests to that endpoint instead of direct DB access.
        
- **Documentation:** Document how to run the crawler service (in `services/crawler/README.md` for example). Include any configuration needed (like environment variables for DB connection or for target URLs). Also note any limitations (e.g., only scrapes one source for now, etc.).
    

**Types of Files to be Created:**

- **Crawler script/module:** e.g., `crawler.py` or a package of modules if using Scrapy (Scrapy will create its own folder structure with a spiders folder).
    
- **Requirements file:** Updated `requirements.txt` with scraping libraries (Scrapy, BeautifulSoup, requests, etc.).
    
- **Configuration files:** Possibly a config file or constants in code for the URLs to scrape, output location, etc. If using Scrapy, settings are in `settings.py` and target domains in the spider definition.
    
- **Database access code:** Either within the script or a separate module (like `db.py`) to handle connecting and inserting into PostgreSQL.
    
- **Logging/output:** Maybe configure logging to a file or console to monitor what the crawler is doing when it runs.
    
- **README.md for Crawler:** describing usage and any setup (like how to install and run it).
    

**File Structure & Key Files (Crawler):**

Under `services/crawler/`, you might have something like:

- `crawler.py`: Main script to start the crawling process. (If using Scrapy, you might instead run `scrapy crawl jobs` via CLI and have a Scrapy project structure.)
    
- `jobs_spider.py`: (If using Scrapy) Spider class defining how to scrape the jobs site – contains the parsing logic for pages.
    
- `db_utils.py`: Database helper functions to insert or update job records in PostgreSQL.
    
- `settings.py`: Configuration for the crawler (user-agent string, obey robots, etc., primarily if using Scrapy).
    
- `requirements.txt`: Lists dependencies for this service (e.g., `scrapy>=2.6`, `psycopg2-binary`, etc.).
    
- `README.md`: Instructions on running the crawler and how it integrates with the main system.
    

The **purpose** of these files: The crawler service runs independently to gather external data. Keeping it separate in its own folder (and possibly process) ensures that the main web app remains decoupled from scraping logic – a good modular design. This means you could replace or update the crawler without touching front-end or main back-end code, improving maintainability. After this phase, you should have a way to feed your application with real job data automatically, which is a key value of the platform.

