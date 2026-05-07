from __future__ import annotations


def build_lexical_query(db, scope):
    from app.api import jobs as jobs_api

    return jobs_api._build_query_from_scope(db, scope)
