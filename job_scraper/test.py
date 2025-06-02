import csv
import random
from jobspy import scrape_jobs

# List of common user agents for randomization
user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

# Select a random user agent
random_user_agent = random.choice(user_agents)

jobs = scrape_jobs(
    site_name=["glassdoor"],
    search_term="ERP",
    # google_search_term="software engineer jobs in Hong Kong",
    location="Hong Kong",
    results_wanted=20,
    hours_old=72,
    country_indeed="Hong Kong",
    user_agent=random_user_agent,
    # linkedin_fetch_description=True # gets more info such as description, direct job url (slower)
    # proxies=["208.195.175.46:65095", "208.195.175.45:65095", "localhost"],
)
print(f"Found {len(jobs)} jobs")
print(jobs.head())
jobs.to_csv(
    "jobs.csv", quoting=csv.QUOTE_NONNUMERIC, escapechar="\\", index=False
)  # to_excel
