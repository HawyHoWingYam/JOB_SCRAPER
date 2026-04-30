from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSearchClause:
    clause_type: str
    value: str


class SearchExpressionError(ValueError):
    def __init__(self, *, message: str, position: int, token: str):
        super().__init__(message)
        self.code = "invalid_search_expression"
        self.message = message
        self.position = position
        self.token = token

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "position": self.position,
            "token": self.token,
        }


def parse_search_expression(text_expression: str | None) -> list[ParsedSearchClause]:
    expression = (text_expression or "").strip()
    if not expression:
        return []

    clauses: list[ParsedSearchClause] = []
    index = 0
    length = len(expression)

    while index < length:
        while index < length and expression[index] in {" ", ","}:
            index += 1

        if index >= length:
            break

        current = expression[index]
        if current == '"':
            end_index = expression.find('"', index + 1)
            if end_index == -1:
                raise SearchExpressionError(
                    message="Unclosed quote in search expression",
                    position=index,
                    token=expression[index:],
                )
            phrase = expression[index + 1:end_index].strip()
            if not phrase:
                raise SearchExpressionError(
                    message="Phrase clauses cannot be empty",
                    position=index,
                    token='""',
                )
            clauses.append(ParsedSearchClause(clause_type="phrase", value=phrase))
            index = end_index + 1
            continue

        if current == "=":
            start_index = index
            index += 1
            while index < length and expression[index] not in {" ", ","}:
                index += 1
            token = expression[start_index + 1:index].strip()
            if not token:
                raise SearchExpressionError(
                    message="Exact clauses must include a token after '='",
                    position=start_index,
                    token="=",
                )
            clauses.append(ParsedSearchClause(clause_type="exact", value=token))
            continue

        start_index = index
        while index < length and expression[index] not in {" ", ","}:
            index += 1
        token = expression[start_index:index].strip()
        if token:
            clauses.append(ParsedSearchClause(clause_type="broad", value=token))

    return clauses
