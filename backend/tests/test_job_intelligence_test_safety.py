import ast
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url


POSTGRESQL_JOB_INTELLIGENCE_SUITES = (
    "integration/test_job_intelligence_rebuild.py",
    "test_canonical_job_taxonomy_api.py",
    "test_canonical_job_taxonomy_governance.py",
    "test_canonical_job_taxonomy_migration.py",
    "test_company_industry_governance.py",
    "test_company_industry_migration.py",
    "test_job_intelligence_foundation.py",
    "test_job_intelligence_response_contracts.py",
    "test_skill_governance.py",
    "test_skill_governance_migration.py",
    "test_source_job_attribute_ingest.py",
    "test_source_job_attributes.py",
)


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
_DATABASE_OPERATION_NAMES = {
    "create_engine",
    "create_all",
    "drop_all",
    "execute",
    "commit",
    "rollback",
    "delete",
    "dispose",
    "upgrade",
    "downgrade",
}


def _is_engine_open(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _call_name(node) == "create_engine"


def _uses_database_url(node: ast.Call) -> bool:
    values = [*node.args, *(keyword.value for keyword in node.keywords)]
    return any(
        isinstance(argument, ast.Name) and argument.id == "database_url"
        for argument in values
    )


def _enclosing_function(
    functions: list[FunctionNode],
    node: ast.AST,
) -> FunctionNode | None:
    if not hasattr(node, "lineno"):
        return None
    node_end = node.end_lineno or node.lineno
    candidates = [
        function
        for function in functions
        if function.lineno <= node.lineno
        and (function.end_lineno or function.lineno) >= node_end
    ]
    return min(
        candidates,
        key=lambda function: (function.end_lineno or function.lineno) - function.lineno,
        default=None,
    )


def _owned_nodes(
    function: FunctionNode,
    functions: list[FunctionNode],
) -> tuple[ast.AST, ...]:
    return tuple(
        node
        for node in ast.walk(function)
        if node is function or _enclosing_function(functions, node) is function
    )


def _line_of_call(
    nodes: tuple[ast.AST, ...],
    *,
    name: str,
    argument: str | None = None,
) -> int | None:
    lines = []
    for node in nodes:
        if not isinstance(node, ast.Call) or _call_name(node) != name:
            continue
        if argument is not None and not any(
            isinstance(value, ast.Constant) and value.value == argument
            for value in node.args
        ):
            continue
        lines.append(node.lineno)
    return min(lines, default=None)


def _is_parsed_database_name(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "database"
        and isinstance(node.value, ast.Call)
        and _call_name(node.value) == "make_url"
        and any(
            isinstance(argument, ast.Name) and argument.id == "database_url"
            for argument in node.value.args
        )
    )


def _line_of_parsed_database_name(nodes: tuple[ast.AST, ...]) -> int | None:
    lines = []
    for node in nodes:
        if _is_parsed_database_name(node):
            lines.append(node.lineno)
    return min(lines, default=None)


def _assigned_parsed_database_names(
    nodes: tuple[ast.AST, ...],
    *,
    before_line: int,
) -> set[str]:
    names = set()
    for node in nodes:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if node.lineno >= before_line:
            continue
        value = node.value
        if value is None or not any(
            _is_parsed_database_name(child) for child in ast.walk(value)
        ):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names.update(
            child.id
            for target in targets
            for child in ast.walk(target)
            if isinstance(child, ast.Name)
        )
    return names


def _suffix_check_uses_parsed_database_name(
    suffix_check: ast.Call,
    nodes: tuple[ast.AST, ...],
    *,
    guard_line: int,
) -> bool:
    assert isinstance(suffix_check.func, ast.Attribute)
    receiver = suffix_check.func.value
    if any(_is_parsed_database_name(child) for child in ast.walk(receiver)):
        return True
    parsed_names = _assigned_parsed_database_names(nodes, before_line=guard_line)
    return any(
        isinstance(child, ast.Name) and child.id in parsed_names
        for child in ast.walk(receiver)
    )


def _test_database_guards(
    nodes: tuple[ast.AST, ...],
) -> tuple[tuple[int, int], ...]:
    guards = []
    for node in nodes:
        if not (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
        ):
            continue
        suffix_checks = [
            child
            for child in ast.walk(node.test)
            if isinstance(child, ast.Call)
            and _call_name(child) == "endswith"
            and any(
                isinstance(argument, ast.Constant) and argument.value == "_test"
                for argument in child.args
            )
            and _suffix_check_uses_parsed_database_name(
                child,
                nodes,
                guard_line=node.lineno,
            )
        ]
        failures = [
            child
            for statement in node.body
            for child in ast.walk(statement)
            if isinstance(child, ast.Call) and _call_name(child) == "fail"
        ]
        if suffix_checks and failures:
            guards.append(
                (
                    min(check.lineno for check in suffix_checks),
                    min(failure.lineno for failure in failures),
                )
            )
    return tuple(sorted(guards))


def test_raw_url_tail_cannot_masquerade_as_a_test_database_name() -> None:
    unsafe_url = "postgresql://localhost/jobsdb?application_name=looks_test"

    assert unsafe_url.rsplit("/", 1)[-1].endswith("_test")
    assert not (make_url(unsafe_url).database or "").endswith("_test")


@pytest.mark.parametrize("relative_path", POSTGRESQL_JOB_INTELLIGENCE_SUITES)
def test_postgresql_suites_guard_test_database_before_opening_engine(
    relative_path: str,
) -> None:
    source = (Path(__file__).parent / relative_path).read_text(encoding="utf-8")
    module = ast.parse(source)
    functions: list[FunctionNode] = [
        node
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    engine_opens = [node for node in ast.walk(module) if _is_engine_open(node)]
    aliased_engine_imports = [
        alias.asname
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == "create_engine" and alias.asname
    ]

    assert (
        not aliased_engine_imports
    ), f"{relative_path} aliases create_engine and bypasses the safety inventory"
    assert engine_opens, f"{relative_path} has no create_engine call"
    assert all(
        _uses_database_url(node) for node in engine_opens
    ), f"{relative_path} must pass the guarded database_url to every create_engine"
    engine_functions: list[FunctionNode] = []
    for engine_open in engine_opens:
        function = _enclosing_function(functions, engine_open)
        assert (
            function is not None
        ), f"{relative_path}:{engine_open.lineno} opens an engine outside a guarded function"
        if function not in engine_functions:
            engine_functions.append(function)

    for function in engine_functions:
        nodes = _owned_nodes(function, functions)
        environment_lookup = _line_of_call(
            nodes,
            name="getenv",
            argument="JOB_INTELLIGENCE_TEST_DATABASE_URL",
        )
        parsed_database_name = _line_of_parsed_database_name(nodes)
        guards = _test_database_guards(nodes)
        operations = sorted(
            (
                node
                for node in nodes
                if isinstance(node, ast.Call)
                and _call_name(node) in _DATABASE_OPERATION_NAMES
            ),
            key=lambda node: (node.lineno, node.col_offset),
        )

        assert (
            environment_lookup is not None
        ), f"{relative_path}:{function.lineno} must read the explicit test URL"
        assert (
            parsed_database_name is not None
        ), f"{relative_path}:{function.lineno} must parse database_url with make_url"
        assert (
            guards
        ), f"{relative_path}:{function.lineno} must fail closed on a *_test suffix check"
        for operation in operations:
            assert any(
                environment_lookup
                < parsed_database_name
                <= test_database_guard
                <= guard_failure
                < operation.lineno
                for test_database_guard, guard_failure in guards
            ), (
                f"{relative_path}:{operation.lineno} opens or mutates PostgreSQL "
                "before the parsed *_test guard"
            )
