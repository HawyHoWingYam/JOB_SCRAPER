## Phase 7: Development of AI Matching Service (Python AI Module)

**Objective & Direction:** Build the **AI-driven matching service** that will analyze job postings and user resumes/preferences to produce match recommendations (e.g., suggest best candidate-job pairs). This is a Python-based service utilizing AI/ML or external AI APIs. The focus is on creating a modular component that can be improved over time but for the prototype provides basic matching functionality. It should integrate with the Nest.js backend or database so that the application can display AI-generated match results to end users (like recommended jobs for a candidate, or best candidates for a job).

**Key Activities:**

- **Define Matching Logic Scope:** Decide what the “AI matching” will do at this prototype stage. It could be:
    
    - Simple keyword matching: e.g., compare skills in a resume to keywords in job descriptions.
        
    - Or integrating an external AI API (the project notes mention a “Gemini API for matching and NLP preprocessing” – you could plan to use a service like GPT or a specialized job matching API).
        
    - Perhaps a two-phase approach: first preprocess data (e.g., extract skills using NLP from resumes and job descriptions), then use a similarity algorithm or ML model to rank matches.
        
- **Set Up AI Service Project:** In `/services/ai_matching/`, set up the Python environment. If using an external API, obtain credentials/config for it. Install necessary libraries (for NLP, maybe `nltk` or `spacy`, or an API SDK).
    
- **Implement Matching Algorithm:** Develop the script or service that takes input (like a user’s profile or resume and a list of job descriptions, or vice versa) and produces a list of relevant matches:
    
    - If using a custom algorithm: you might vectorize text (skills, job requirements) and compute cosine similarity, or use a simple rule-based score.
        
    - If using an API: send the data to the API and receive the results. This could involve formatting a prompt or request for something like GPT-4 to get match suggestions.
        
    - Ensure the output is structured (e.g., a list of job IDs for a given user, or for a given job a list of user IDs ranked).
        
- **Design Service Interface:** Decide how the Nest.js backend will use this matching logic:
    
    - One way: create a small web service (using Flask or FastAPI) that runs in `ai_matching` and exposes an endpoint (e.g., `POST /match` with either a user or job as input, responds with a list of matches). The Nest backend can then call this HTTP endpoint when it needs match results (such as when an admin wants to view match statistics, or when a user asks for recommended jobs).
        
    - Simpler way (for prototype): run the matching as an offline script that writes results to the database. For example, a script that periodically computes top matches for all users and saves them in a `matches` table (userID, jobID, score). But on-demand via an API call is more dynamic.
        
    - If time permits, implement the Flask/FastAPI service method for real-time calls. Otherwise, you can simulate by computing once and querying the DB.
        
- **Database Integration:** If you need to store results, consider a new table e.g. `match_scores` or similar, or add a field to existing tables (not recommended for many-to-many matches). If an API call is quick enough, you might not need to store – just compute on request.
    
    - For the prototype, perhaps implement a simple call: e.g., when a user visits a "Recommended Jobs" page, the front-end calls Nest (something like GET `/users/{id}/recommendations`). Nest’s controller will in turn call the Python AI service (via HTTP) with that user’s data, get back some job recommendations, and return to the front-end. This avoids storing data and keeps it real-time.
        
- **Testing the AI Logic:** If possible, test the matching with sample data:
    
    - Feed a sample resume text and a job description to your function/API and see if the output makes sense (e.g., does it identify a match correctly?).
        
    - If using an external API, test the response format and parse it as needed.
        
    - Ensure that if the AI service is down or fails, the system can handle it gracefully (maybe the Nest endpoint returns an error or an empty list with a message "Matching service not available").
        
- **Secure the Integration:** If the AI service is an open API endpoint (Flask app), consider securing it (even basic token auth or allow only localhost) since it’s internal. For a prototype, this might be skipped, but note it.
    
- **Documentation:** Document how the AI service works and how to run it (e.g., `services/ai_matching/README.md`). If there are any model files or significant processing, note those. Document any new API endpoints in Nest that were added to integrate this service (for example, an admin endpoint to trigger recalculation of all matches, or user-specific recommendation endpoint).
    
- **Modular Consideration:** Keep this AI logic decoupled; the idea is that the main application can function without it (e.g., if the service is off, users can still search manually). This way, the AI module is an add-on that can be improved or replaced without altering core front-end/back-end code.
    

**Types of Files to be Created:**

- **AI service script/app:** e.g., `app.py` (if using Flask) or `main.py` for a FastAPI app. This will define endpoints like `/match`.
    
- **Matching logic module:** e.g., `matcher.py` containing functions to compute matches given input data.
    
- **NLP/ML model or data files:** If using a library or model (e.g., a spaCy model or pickled ML model), those need to be included or referenced. Possibly a `models/` folder or downloading a model in setup.
    
- **Requirements file:** Update `requirements.txt` with any new libraries (e.g., `spacy`, `pandas`, `openai` for API, etc.).
    
- **Configuration:** If calling an external API, you might have an `api_keys.env` or simply require an environment variable for the API key (ensure not to hardcode keys).
    
- **Test data:** Maybe a sample resume text and job description in a `data/` folder for development testing.
    

**File Structure & Key Files (AI Service):**

In `services/ai_matching/` folder:

- `app.py` (or `api.py`): Flask/FastAPI application definition. For example, a Flask app might have:
    
    ```python
    @app.route('/match', methods=['POST'])
    def match():
        # expects JSON like {"userId": X} or {"jobId": Y}
        # calls matching logic and returns results
    ```
    
- `matcher.py`: Contains the core logic for matching. For example, a function `match_user_to_jobs(user_profile) -> list[jobIds]`. If using an external AI, this module handles the API call and processing of results.
    
- `models/` (optional): Directory for any AI models or data files needed (could include NLP model data or pretrained embeddings if used).
    
- `requirements.txt`: Lists required Python packages (e.g., `flask`, `spacy`, `openai`, etc., depending on approach).
    
- `README.md`: Documentation on how to run the AI service (e.g., “Run `flask run` after setting environment variables X, Y…”).
    

On the **Nest.js side (backend)**, integrate with one or two new files:

- Possibly an `AiController` or service within Nest:
    
    - e.g., `ai.controller.ts` with an endpoint `GET /ai/recommendations/:userId` that calls the Python service.
        
    - Or add a method in `users.controller.ts` for `/users/:id/recommendations`.
        
    - This Nest code will use `HttpService` (from Nest or axios) to call `http://localhost:<port>/match` with the necessary data.
        
    - Ensure to handle the response and send it to front-end in a friendly format.
        

The key purpose of these AI service files is to encapsulate the **intelligence** of the platform in a standalone module. By keeping it separate (much like the crawler), you adhere to a modular architecture – the AI logic can be worked on independently, scaled separately, or even replaced by a third-party service without major changes to the rest of the system. By end of this phase, your platform will be enriched with a unique feature: AI-driven matching, making it stand out as a smart recruitment prototype.
