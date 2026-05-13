import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.scraper.ctgoodjobs.category_registry import parse_category_registry


def test_parse_category_registry_extracts_jobcats_from_non_json_next_payload():
    page_html = """
    <html><body>
    <script>
    self.__next_f.push([1,"1b:[[\\"$\\",\\"$L35\\",null,{}],[\\"$\\",\\"$L38\\",null,{\\"filter\\":{\\"JobFunction\\":[]},\\"jobcats\\":[{\\"total\\":12,\\"id\\":\\"001_jc\\",\\"name\\":\\"Accounting / Auditing\\",\\"nameForUrl\\":\\"accounting-auditing\\"},{\\"total\\":34,\\"id\\":\\"021_jc\\",\\"name\\":\\"Information Technology (IT)\\",\\"nameForUrl\\":\\"information-technology\\"}],\\"jobFunctions\\":[]}]]"]);
    </script>
    </body></html>
    """

    categories = parse_category_registry(page_html)

    assert len(categories) == 2
    assert categories[0].source_classification_id == "ctgoodjobs:001"
    assert categories[0].slug == "accounting-auditing"
    assert categories[1].source_classification_id == "ctgoodjobs:021"
    assert categories[1].slug == "information-technology"
