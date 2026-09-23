# Phase 5 incident triage design

Frozen events become secret-safe observations. Deterministic clustering happens
before any model use. A cluster retains all event sequence references and raw
evidence hashes, but model state receives only allowlisted source/phase/class/
code/count/time and a bounded normalized symptom. Advice never enters the crawl
state machine or action dispatcher. Provider failure returns the unprioritized
deterministic cluster list.
