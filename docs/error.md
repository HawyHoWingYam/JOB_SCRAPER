2026-05-08 16:11:28.281 | INFO:     Will watch for changes in these directories: ['/app']
2026-05-08 16:11:28.281 | INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
2026-05-08 16:11:28.281 | INFO:     Started reloader process [1] using WatchFiles
2026-05-08 16:11:32.602 | INFO:     Started server process [8]
2026-05-08 16:11:32.602 | INFO:     Waiting for application startup.
2026-05-08 16:11:32.602 | 2026-05-08 08:11:32,602 INFO [app.main] Starting JobsDB Scraper API
2026-05-08 16:11:32.602 | 2026-05-08 08:11:32,602 INFO [app.main] Debug mode: True
2026-05-08 16:11:32.603 | 2026-05-08 08:11:32,602 INFO [app.main] Database: postgresql://admin:***@postgres-db:5432/jobsdb
2026-05-08 16:11:32.728 | 2026-05-08 08:11:32,727 INFO [app.main] Startup recovery summary: {'ai_runs_recovered': 0, 'company_runs_recovered': 0, 'crawl_jobs_recovered': 0, 'schedule_executions_recovered': 0}
2026-05-08 16:11:32.728 | 2026-05-08 08:11:32,728 INFO [app.services.scheduler_service] Initializing scheduler service...
2026-05-08 16:11:32.751 | 2026-05-08 08:11:32,750 INFO [apscheduler.scheduler] Scheduler started
2026-05-08 16:11:32.755 | 2026-05-08 08:11:32,754 INFO [app.services.scheduler_service] Loaded 0 active schedules
2026-05-08 16:11:32.755 | 2026-05-08 08:11:32,755 INFO [app.services.scheduler_service] Scheduler service initialized
2026-05-08 16:11:32.762 | INFO:     Application startup complete.
2026-05-08 16:25:06.700 | INFO:     172.18.0.6:42334 - "GET /api/v1/stats/overview HTTP/1.1" 200 OK
2026-05-08 16:25:06.799 | INFO:     172.18.0.6:42348 - "GET /api/v1/ai/overview HTTP/1.1" 200 OK
2026-05-08 16:25:06.820 | INFO:     172.18.0.6:42356 - "GET /api/v1/stats/overview HTTP/1.1" 200 OK
2026-05-08 16:25:06.839 | INFO:     172.18.0.6:42368 - "GET /api/v1/ai/overview HTTP/1.1" 200 OK
2026-05-08 16:25:07.139 | INFO:     172.18.0.6:42372 - "GET /api/v1/stats/skills?limit=30 HTTP/1.1" 200 OK
2026-05-08 16:25:07.250 | INFO:     172.18.0.6:42382 - "GET /api/v1/stats/categories/dashboard HTTP/1.1" 200 OK
2026-05-08 16:25:07.263 | INFO:     172.18.0.6:42390 - "GET /api/v1/stats/skills?limit=30 HTTP/1.1" 200 OK
2026-05-08 16:25:07.281 | INFO:     172.18.0.6:42392 - "GET /api/v1/stats/categories/dashboard HTTP/1.1" 200 OK
2026-05-08 16:35:51.572 | INFO:     172.18.0.6:43192 - "GET /api/v1/ai/overview HTTP/1.1" 200 OK
2026-05-08 16:35:51.606 | INFO:     172.18.0.6:43206 - "GET /api/v1/stats/overview HTTP/1.1" 200 OK
2026-05-08 16:35:51.669 | INFO:     172.18.0.6:43218 - "GET /api/v1/ai/overview HTTP/1.1" 200 OK
2026-05-08 16:35:51.677 | INFO:     172.18.0.6:43232 - "GET /api/v1/stats/overview HTTP/1.1" 200 OK
2026-05-08 16:35:51.737 | INFO:     172.18.0.6:43238 - "GET /api/v1/stats/skills?limit=30 HTTP/1.1" 200 OK
2026-05-08 16:35:51.779 | INFO:     172.18.0.6:43246 - "GET /api/v1/stats/categories/dashboard HTTP/1.1" 200 OK
2026-05-08 16:35:51.800 | INFO:     172.18.0.6:43256 - "GET /api/v1/stats/skills?limit=30 HTTP/1.1" 200 OK
2026-05-08 16:35:51.814 | INFO:     172.18.0.6:43272 - "GET /api/v1/stats/categories/dashboard HTTP/1.1" 200 OK
2026-05-08 16:37:24.289 | INFO:     172.18.0.6:41658 - "GET /api/v1/stats/overview HTTP/1.1" 200 OK
2026-05-08 16:37:24.311 | INFO:     172.18.0.6:41674 - "GET /api/v1/ai/overview HTTP/1.1" 200 OK
2026-05-08 16:37:24.348 | INFO:     172.18.0.6:41686 - "GET /api/v1/ai/overview HTTP/1.1" 200 OK
2026-05-08 16:37:24.364 | INFO:     172.18.0.6:41698 - "GET /api/v1/stats/overview HTTP/1.1" 200 OK
2026-05-08 16:37:24.378 | INFO:     172.18.0.6:41714 - "GET /api/v1/stats/skills?limit=30 HTTP/1.1" 200 OK
2026-05-08 16:37:24.391 | INFO:     172.18.0.6:41716 - "GET /api/v1/stats/categories/dashboard HTTP/1.1" 200 OK
2026-05-08 16:37:24.409 | INFO:     172.18.0.6:41718 - "GET /api/v1/stats/skills?limit=30 HTTP/1.1" 200 OK
2026-05-08 16:37:24.419 | INFO:     172.18.0.6:41728 - "GET /api/v1/stats/categories/dashboard HTTP/1.1" 200 OK
2026-05-08 16:37:26.924 | INFO:     172.18.0.6:41760 - "GET /api/v1/jobs/filters HTTP/1.1" 200 OK
2026-05-08 16:37:27.140 | INFO:     172.18.0.6:41740 - "POST /api/v1/jobs/search HTTP/1.1" 200 OK
2026-05-08 16:37:27.157 | INFO:     172.18.0.6:41776 - "POST /api/v1/jobs/search HTTP/1.1" 200 OK
2026-05-08 16:37:27.191 | INFO:     172.18.0.6:41784 - "GET /api/v1/jobs/filters HTTP/1.1" 200 OK
2026-05-08 16:37:27.211 | INFO:     172.18.0.6:41752 - "GET /api/v1/filters/job-subcategories HTTP/1.1" 200 OK
2026-05-08 16:37:27.226 | INFO:     172.18.0.6:41790 - "GET /api/v1/filters/job-subcategories HTTP/1.1" 200 OK
2026-05-08 16:37:30.406 | INFO:     172.18.0.6:41802 - "GET /api/v1/companies?status=pending&page=1&page_size=25 HTTP/1.1" 200 OK
2026-05-08 16:37:30.428 | INFO:     172.18.0.6:41818 - "GET /api/v1/companies/enrichment-runs/current HTTP/1.1" 200 OK
2026-05-08 16:37:30.441 | INFO:     172.18.0.6:41820 - "GET /api/v1/companies?status=pending&page=1&page_size=25 HTTP/1.1" 200 OK
2026-05-08 16:37:30.453 | INFO:     172.18.0.6:41828 - "GET /api/v1/companies/enrichment-runs/current HTTP/1.1" 200 OK
2026-05-08 16:37:31.900 | INFO:     172.18.0.6:41852 - "GET /api/v1/scrape/progress HTTP/1.1" 200 OK
2026-05-08 16:37:31.938 | INFO:     172.18.0.6:41830 - "GET /api/v1/schedules HTTP/1.1" 200 OK
2026-05-08 16:37:31.939 | INFO:     172.18.0.6:41836 - "GET /api/categories?source_site=jobsdb HTTP/1.1" 200 OK
2026-05-08 16:37:31.948 | INFO:     172.18.0.6:41866 - "GET /api/v1/scrape/progress HTTP/1.1" 200 OK
2026-05-08 16:37:31.960 | INFO:     172.18.0.6:41876 - "GET /api/v1/schedules HTTP/1.1" 200 OK
2026-05-08 16:37:31.966 | INFO:     172.18.0.6:41878 - "GET /api/categories?source_site=jobsdb HTTP/1.1" 200 OK
2026-05-08 16:37:43.072 | INFO:     172.18.0.6:46054 - "POST /api/v1/crawl-jobs HTTP/1.1" 202 Accepted
2026-05-08 16:37:43.145 | INFO:     172.18.0.6:46070 - "GET /api/v1/scrape/progress/stream HTTP/1.1" 200 OK
2026-05-10 15:11:43.796 | Traceback (most recent call last):
2026-05-10 15:11:43.797 |   File "/usr/local/bin/uvicorn", line 7, in <module>
2026-05-10 15:11:43.822 |     sys.exit(main())
2026-05-10 15:11:43.822 |              ^^^^^^
2026-05-10 15:11:43.822 |   File "/usr/local/lib/python3.12/dist-packages/click/core.py", line 1514, in __call__
2026-05-10 15:11:43.828 |     return self.main(*args, **kwargs)
2026-05-10 15:11:43.829 |            ^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-05-10 15:11:43.829 |   File "/usr/local/lib/python3.12/dist-packages/click/core.py", line 1435, in main
2026-05-10 15:11:43.830 |     rv = self.invoke(ctx)
2026-05-10 15:11:43.832 |          ^^^^^^^^^^^^^^^^
2026-05-10 15:11:43.832 |   File "/usr/local/lib/python3.12/dist-packages/click/core.py", line 1298, in invoke
2026-05-10 15:11:43.832 |     return ctx.invoke(self.callback, **ctx.params)
2026-05-10 15:11:43.836 |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-05-10 15:11:43.836 |   File "/usr/local/lib/python3.12/dist-packages/click/core.py", line 853, in invoke
2026-05-10 15:11:43.837 |     return callback(*args, **kwargs)
2026-05-10 15:11:43.837 |            ^^^^^^^^^^^^^^^^^^^^^^^^^
2026-05-10 15:11:43.838 |   File "/usr/local/lib/python3.12/dist-packages/uvicorn/main.py", line 416, in main
2026-05-10 15:11:43.840 |     run(
2026-05-10 15:11:43.841 |   File "/usr/local/lib/python3.12/dist-packages/uvicorn/main.py", line 582, in run
2026-05-10 15:11:43.841 |     ChangeReload(config, target=server.run, sockets=[sock]).run()
2026-05-10 15:11:43.845 |   File "/usr/local/lib/python3.12/dist-packages/uvicorn/supervisors/basereload.py", line 50, in run
2026-05-10 15:11:43.847 |     for changes in self:
2026-05-10 15:11:43.847 |   File "/usr/local/lib/python3.12/dist-packages/uvicorn/supervisors/basereload.py", line 69, in __next__
2026-05-10 15:11:43.847 |     return self.should_restart()
2026-05-10 15:11:43.848 |            ^^^^^^^^^^^^^^^^^^^^^
2026-05-10 15:11:43.849 |   File "/usr/local/lib/python3.12/dist-packages/uvicorn/supervisors/watchfilesreload.py", line 87, in should_restart
2026-05-10 15:11:43.850 |     changes = next(self.watcher)
2026-05-10 15:11:43.851 |               ^^^^^^^^^^^^^^^^^^
2026-05-10 15:11:43.852 |   File "/usr/local/lib/python3.12/dist-packages/watchfiles/main.py", line 130, in watch
2026-05-10 15:11:43.854 |     raw_changes = watcher.watch(debounce, step, rust_timeout, stop_event)
2026-05-10 15:11:43.857 |                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-05-10 15:11:43.859 | _rust_notify.WatchfilesRustInternalError: error in underlying watcher: IO error for operation on /app: Input/output error (os error 5) about ["/app"]
2026-05-11 11:13:01.737 | INFO:     Will watch for changes in these directories: ['/app']
2026-05-11 11:13:01.737 | INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
2026-05-11 11:13:01.737 | INFO:     Started reloader process [1] using WatchFiles
2026-05-11 11:13:04.522 | INFO:     Started server process [8]
2026-05-11 11:13:04.522 | INFO:     Waiting for application startup.
2026-05-11 11:13:04.523 | 2026-05-11 03:13:04,522 INFO [app.main] Starting JobsDB Scraper API
2026-05-11 11:13:04.523 | 2026-05-11 03:13:04,523 INFO [app.main] Debug mode: True
2026-05-11 11:13:04.523 | 2026-05-11 03:13:04,523 INFO [app.main] Database: postgresql://admin:***@postgres-db:5432/jobsdb
2026-05-11 11:13:04.641 | 2026-05-11 03:13:04,641 INFO [app.main] Startup recovery summary: {'ai_runs_recovered': 0, 'company_runs_recovered': 0, 'crawl_jobs_recovered': 0, 'schedule_executions_recovered': 0}
2026-05-11 11:13:04.642 | 2026-05-11 03:13:04,641 INFO [app.services.scheduler_service] Initializing scheduler service...
2026-05-11 11:13:04.661 | 2026-05-11 03:13:04,661 INFO [apscheduler.scheduler] Scheduler started
2026-05-11 11:13:04.670 | 2026-05-11 03:13:04,669 INFO [app.services.scheduler_service] Loaded 0 active schedules
2026-05-11 11:13:04.670 | 2026-05-11 03:13:04,670 INFO [app.services.scheduler_service] Scheduler service initialized
2026-05-11 11:13:04.678 | INFO:     Application startup complete.
2026-05-11 18:08:09.996 | Traceback (most recent call last):
2026-05-11 18:08:10.004 |   File "/usr/local/bin/uvicorn", line 7, in <module>
2026-05-11 18:08:10.040 |     sys.exit(main())
2026-05-11 18:08:10.044 |              ^^^^^^
2026-05-11 18:08:10.044 |   File "/usr/local/lib/python3.12/dist-packages/click/core.py", line 1514, in __call__
2026-05-11 18:08:10.053 |     return self.main(*args, **kwargs)
2026-05-11 18:08:10.054 |            ^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-05-11 18:08:10.054 |   File "/usr/local/lib/python3.12/dist-packages/click/core.py", line 1435, in main
2026-05-11 18:08:10.054 |     rv = self.invoke(ctx)
2026-05-11 18:08:10.055 |          ^^^^^^^^^^^^^^^^
2026-05-11 18:08:10.055 |   File "/usr/local/lib/python3.12/dist-packages/click/core.py", line 1298, in invoke
2026-05-11 18:08:10.055 |     return ctx.invoke(self.callback, **ctx.params)
2026-05-11 18:08:10.056 |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-05-11 18:08:10.056 |   File "/usr/local/lib/python3.12/dist-packages/click/core.py", line 853, in invoke
2026-05-11 18:08:10.056 |     return callback(*args, **kwargs)
2026-05-11 18:08:10.057 |            ^^^^^^^^^^^^^^^^^^^^^^^^^
2026-05-11 18:08:10.057 |   File "/usr/local/lib/python3.12/dist-packages/uvicorn/main.py", line 416, in main
2026-05-11 18:08:10.057 |     run(
2026-05-11 18:08:10.058 |   File "/usr/local/lib/python3.12/dist-packages/uvicorn/main.py", line 582, in run
2026-05-11 18:08:10.058 |     ChangeReload(config, target=server.run, sockets=[sock]).run()
2026-05-11 18:08:10.060 |   File "/usr/local/lib/python3.12/dist-packages/uvicorn/supervisors/basereload.py", line 50, in run
2026-05-11 18:08:10.061 |     for changes in self:
2026-05-11 18:08:10.061 |   File "/usr/local/lib/python3.12/dist-packages/uvicorn/supervisors/basereload.py", line 69, in __next__
2026-05-11 18:08:10.061 |     return self.should_restart()
2026-05-11 18:08:10.062 |            ^^^^^^^^^^^^^^^^^^^^^
2026-05-11 18:08:10.063 |   File "/usr/local/lib/python3.12/dist-packages/uvicorn/supervisors/watchfilesreload.py", line 87, in should_restart
2026-05-11 18:08:10.064 |     changes = next(self.watcher)
2026-05-11 18:08:10.065 |               ^^^^^^^^^^^^^^^^^^
2026-05-11 18:08:10.066 |   File "/usr/local/lib/python3.12/dist-packages/watchfiles/main.py", line 130, in watch
2026-05-11 18:08:10.068 |     raw_changes = watcher.watch(debounce, step, rust_timeout, stop_event)
2026-05-11 18:08:10.069 |                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-05-11 18:08:10.070 | _rust_notify.WatchfilesRustInternalError: error in underlying watcher: IO error for operation on /app: Bad address (os error 14) about ["/app"]
2026-05-12 16:33:44.534 | INFO:     Will watch for changes in these directories: ['/app']
2026-05-12 16:33:44.534 | INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
2026-05-12 16:33:44.535 | INFO:     Started reloader process [1] using WatchFiles
2026-05-12 16:34:07.280 | INFO:     Started server process [8]
2026-05-12 16:34:07.280 | INFO:     Waiting for application startup.
2026-05-12 16:34:07.282 | 2026-05-12 08:34:07,281 INFO [app.main] Starting JobsDB Scraper API
2026-05-12 16:34:07.282 | 2026-05-12 08:34:07,282 INFO [app.main] Debug mode: True
2026-05-12 16:34:07.282 | 2026-05-12 08:34:07,282 INFO [app.main] Database: postgresql://admin:***@postgres-db:5432/jobsdb
2026-05-12 16:34:07.916 | 2026-05-12 08:34:07,916 INFO [app.main] Startup recovery summary: {'ai_runs_recovered': 0, 'company_runs_recovered': 0, 'crawl_jobs_recovered': 0, 'schedule_executions_recovered': 0}
2026-05-12 16:34:07.916 | 2026-05-12 08:34:07,916 INFO [app.services.scheduler_service] Initializing scheduler service...
2026-05-12 16:34:08.002 | 2026-05-12 08:34:08,001 INFO [apscheduler.scheduler] Scheduler started
2026-05-12 16:34:08.024 | 2026-05-12 08:34:08,023 INFO [app.services.scheduler_service] Loaded 0 active schedules
2026-05-12 16:34:08.025 | 2026-05-12 08:34:08,024 INFO [app.services.scheduler_service] Scheduler service initialized
2026-05-12 16:34:08.042 | INFO:     Application startup complete.
2026-05-12 16:44:52.379 | INFO:     172.18.0.8:57960 - "GET /api/v1/ai/overview HTTP/1.1" 200 OK
2026-05-12 16:44:52.792 | INFO:     172.18.0.8:57966 - "GET /api/v1/stats/overview HTTP/1.1" 200 OK
2026-05-12 16:44:52.823 | INFO:     172.18.0.8:36220 - "GET /api/v1/stats/overview HTTP/1.1" 200 OK
2026-05-12 16:44:52.869 | INFO:     172.18.0.8:36228 - "GET /api/v1/ai/overview HTTP/1.1" 200 OK
2026-05-12 16:44:53.566 | INFO:     172.18.0.8:36242 - "GET /api/v1/stats/skills?limit=30 HTTP/1.1" 200 OK
2026-05-12 16:44:53.790 | INFO:     172.18.0.8:36248 - "GET /api/v1/stats/categories/dashboard HTTP/1.1" 200 OK
2026-05-12 16:44:53.802 | INFO:     172.18.0.8:36252 - "GET /api/v1/stats/skills?limit=30 HTTP/1.1" 200 OK
2026-05-12 16:44:53.833 | INFO:     172.18.0.8:36254 - "GET /api/v1/stats/categories/dashboard HTTP/1.1" 200 OK
2026-05-12 16:45:00.965 | INFO:     172.18.0.8:36284 - "GET /api/v1/scrape/progress HTTP/1.1" 200 OK
2026-05-12 16:45:00.967 | INFO:     172.18.0.8:36262 - "GET /api/categories?source_site=jobsdb HTTP/1.1" 200 OK
2026-05-12 16:45:01.038 | INFO:     172.18.0.8:36272 - "GET /api/v1/schedules HTTP/1.1" 200 OK
2026-05-12 16:45:01.052 | INFO:     172.18.0.8:36288 - "GET /api/v1/scrape/progress HTTP/1.1" 200 OK
2026-05-12 16:45:01.097 | INFO:     172.18.0.8:36306 - "GET /api/v1/scrape/progress/stream HTTP/1.1" 200 OK
2026-05-12 16:45:01.118 | INFO:     172.18.0.8:36290 - "GET /api/categories?source_site=jobsdb HTTP/1.1" 200 OK
2026-05-12 16:45:01.134 | INFO:     172.18.0.8:36320 - "GET /api/v1/schedules HTTP/1.1" 200 OK
2026-05-12 16:45:50.755 | INFO:     172.18.0.8:60078 - "POST /api/v1/crawl-jobs HTTP/1.1" 202 Accepted