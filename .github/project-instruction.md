## 1. Frontend (React.js + Material-UI + Redux)

### Code Structure and Best Practices:
Organize frontend code by **feature modules**, including React components, Redux slices/reducers, and relevant styles. This maintains clear separation of concerns and enhances maintainability. Common components and utilities should reside in a `common` or `shared` directory for reuse between client and portal applications. With Material-UI, create a unified theme file and use ThemeProvider for global styling to ensure consistent visual style across modules.

### Client and Portal Module Separation:
Distinguish between frontend user roles such as job-seekers (client) and recruiters (portal). Consider either a single codebase differentiated by routing, or two separate frontend applications. Shared components like navigation and forms should be extracted into a common module. For larger projects, a micro-frontend architecture could be employed, although early projects may use routing-based differentiation for simplicity.

### API Calls and State Management Optimization:
Manage global state using Redux with middleware for asynchronous API calls (Redux Thunk or Redux Saga). Follow Redux best practices by storing normalized, flat-structured data, and avoid redundancy. Use normalization tools like `normalizr` to standardize data and leverage selectors for derived state. Implement caching strategies in Redux to avoid unnecessary requests. Utilize Material-UI components to streamline development, and separate container components (handling logic and Redux state) from presentational components (displaying data).

---

## 2. Backend (Nest.js + PostgreSQL + Redis)

### Code Organization and Modularization:
Adopt Nest.js modular architecture by defining clear domain modules (e.g., `JobsModule`, `UsersModule`, `ApplicationsModule`). Each module contains Controllers, Services, Entities, and DTOs, with interactions managed via imports and dependency injection. Utilize MVC patterns to maintain clean, maintainable code.

### API Design (REST + GraphQL):
Support both RESTful and GraphQL APIs. REST APIs manage standard CRUD operations clearly (`GET /api/v1/jobs`), while GraphQL handles complex, nested queries. Nest.js seamlessly supports both by sharing business logic across GraphQL resolvers and REST controllers. Consider GraphQL-first approaches for complex scenarios, reducing duplicate implementations.

### Database Design:
Use PostgreSQL with structured tables:
- **Job Table**: Fields include job ID, department, title, description, job type, location, active status, dates, company ID, etc.
- **User & Resume Tables**: Separate user information (ID, name, email, password, roles) and resume details (education, experience, skills). Resumes may store structured data or file paths.
- **Application Table**: Track job applications, status, applicant details, and cover letters.

### Cache Strategy (Redis):
Leverage Redis for caching frequently accessed data (popular job lists, homepage statistics). Implement cache invalidation upon updates and use Redis for session/token management.

### API Versioning and Rate Limiting:
Use Nest.js URI versioning (`/api/v1/...`) to manage API evolution without disrupting existing clients. Utilize Nest's built-in `@nestjs/throttler` module for rate limiting to prevent abuse and enhance security.

---

## 3. Web Crawling (Python + Scrapy + Selenium + Proxy Pool)

### Scrapy Structure Optimization and Data Cleaning:
Use Scrapy to build spiders per recruitment site, with clearly defined items and pipelines for cleaning data (HTML removal, salary parsing, field validation). Optimize concurrency and delays to avoid being blocked.

### Proxy Pool Selection and Configuration:
Integrate a proxy rotation middleware (like `scrapy-rotating-proxies`) to avoid IP blocking. Manage proxies via paid services or open-source proxies. Implement retry mechanisms for failed proxies to maintain efficiency.

### Selenium as a Fallback:
Use Selenium when content dynamically loads with JavaScript or when anti-scraping measures block standard requests. Scrapy first attempts direct fetches; if data is missing, switch to Selenium headless browsing. Limit Selenium usage for critical cases due to overhead.

---

## 4. AI Analysis (Python + Gemini API + NLP Preprocessing)

### NLP Preprocessing Workflow:
Perform text extraction, cleaning, tokenization (spaCy, Jieba), lemmatization, stop-word removal, and Named Entity Recognition (NER) to identify key details from resumes/job descriptions. Extract keywords or vectorize texts (using embeddings) for improved matching and retrieval.

### OCR Technology Selection:
Choose OCR based on accuracy, speed, and cost:
- **Tesseract OCR**: Open-source, cost-effective but requires customization.
- **Cloud OCR services**: High accuracy (Google Vision, Azure Form Recognizer), convenient but at a cost.
- **Dedicated resume parsing APIs**: Efficient but typically expensive (e.g., Affinda, Rchilli).

### Gemini API Invocation and Analysis:
Use preprocessed data to call the Gemini AI API via Python (requests library). Handle concurrency and errors gracefully, possibly using message queues to decouple processing. Store results (matching scores, recommended candidates) for future reference.

### Storing and Querying AI Results:
Store AI-derived matches and scores in structured tables or vector databases (Milvus, Faiss) for quick candidate-job matching retrieval. Periodically update results to maintain accuracy.

---

## 5. File Upload and Storage (Nest.js + Multer + Azure Blob Storage)

### Multer for File Upload:
Nest.js integrates Multer to handle uploads (`multipart/form-data`). Configure Multer options for memory storage, size/type validations, and security measures to protect against malicious uploads.

### Azure Blob Storage Integration:
Immediately transfer uploaded files from memory to Azure Blob Storage using Node SDK (`@azure/storage-blob`). Files are referenced via secure URLs or SAS tokens, preventing local server storage overhead.

### File Preprocessing and Security:
Implement MIME validation, virus scanning, sensitive content filtering, and controlled file access (SAS Tokens). Log all file activities for auditing. Use secure naming conventions (UUIDs) and structured paths.

---

## 6. CI/CD and Docker Compose

### Docker Compose for Local Environment:
Use Docker Compose to orchestrate frontend, backend, database, Redis, crawlers, and other services in a reproducible local environment. Define clear service dependencies and network isolation.

### GitHub Actions for Docker Builds:
Automate Docker builds on code push using GitHub Actions. Publish built images to Docker Hub or Azure container registries with clear version tags. Integrate unit and integration testing into CI pipelines for robust deployments.

### Cloud Deployment Automation:
Deploy automatically built images using orchestration tools (Kubernetes, Docker Compose on VM) or cloud-native solutions (Azure Web Apps, AWS ECS). Integrate securely stored credentials and manage deployment configurations clearly. Implement notifications and rollback strategies.

---

## 7. Monitoring and Log Management

### Web Crawling Task Monitoring:
Monitor Scrapy tasks through built-in logging, job scheduling services (Scrapyd), and custom dashboards. Implement error detection for frequent failures and blockage alerts (e.g., HTTP 403/429 status codes).

### API Requests and AI Analysis Monitoring:
Adopt Application Performance Monitoring (APM) tools (Datadog, New Relic) for API request monitoring, logging metrics like response times, throughput, and errors. Monitor AI task queue lengths and third-party API stability (Gemini API). Include container-level resource monitoring.

### Log Aggregation and Error Management Best Practices:
Centralize logs using ELK (Elasticsearch, Logstash, Kibana), Azure Monitor, or AWS CloudWatch. Adopt structured logging formats (JSON), standardize log levels (debug, info, warning, error), and mask sensitive data. Implement Nest.js exception filters to standardize error handling and responses. Integrate error-tracking tools (e.g., Sentry) for real-time alerts and efficient troubleshooting.
