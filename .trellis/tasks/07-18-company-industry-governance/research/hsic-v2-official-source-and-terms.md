# HSIC V2.0 official source and reuse terms

Access date: 2026-07-19 (Asia/Shanghai).

## Authoritative release and structure

The Hong Kong Census and Statistics Department (C&SD) identifies the Hong Kong
Standard Industrial Classification Version 2.0 (HSIC V2.0) as its classification
of Hong Kong economic units by major economic activity. The official overview
states that HSIC V2.0 was released in 2008, has been used since 2009, is modelled
on ISIC Rev.4, and has five levels:

| Level | Official count | Code form |
| --- | ---: | --- |
| Industry Section | 21 | `A`–`U` |
| Industry Division | 88 | two digits |
| Industry Group | 221 | three digits |
| Industry Class | 483 | four digits |
| Industry Sub-class | 1,001 | six digits |

Primary source: <https://www.censtatd.gov.hk/en/page_698.html>.

The official page links both a bilingual index/manual and the public HSIC V2.0
search tool. The search tool obtains the complete hierarchy as JSON from:

<https://www.censtatd.gov.hk/search/index.php?lang_search=en&l=web&c=HsicCode&m=structure>

The response contains `queryArray1` through `queryArray5`, with official code,
English title, Traditional Chinese title, Simplified Chinese title, and
descriptions. On 2026-07-19 its SHA-256 was
`1c774d8cbb9693a6add2f662683a3c5249bccb6999ccb52dabf6d07a18ef91b7`, and its
array counts matched the official `21/88/221/483/1001` totals. The endpoint is a
public implementation detail of the search tool, so the repository keeps the
source URL, retrieval date, raw checksum, generated-seed checksum, and a
deterministic rebuild script rather than assuming the endpoint is permanent.

The official bilingual index metadata is also published at:

- <https://www.censtatd.gov.hk/en/EIndexbySubject.html?pcode=B2XX0021&scode=452>
- <https://www.censtatd.gov.hk/en/data/stat_report/product/B2XX0021/report_element.json>

## Intellectual-property and redistribution terms

C&SD's official Important Notices explicitly include “classifications” in
“Statistical Information”. Paragraph 2 permits visitors to download, print,
adapt, distribute, reproduce, and hyperlink that Statistical Information free
of charge for commercial and non-commercial purposes. Paragraph 4 requires:

1. acknowledgement of the C&SD website as source;
2. acknowledgement of the Government of the Hong Kong SAR as the intellectual
   property-rights owner; and
3. clear identification of modifications.

The permission does not extend to third-party material or excluded media such
as maps, photographs, graphics, drawings, logos, audio, and video. The derived
seed uses the classification code/title data only.

Primary source: <https://www.censtatd.gov.hk/en/page_31.html>, paragraphs 1–7.

## Repository compliance contract

- Attribute the source to C&SD and the rights owner to the Government of the
  Hong Kong SAR next to the generated seed.
- Mark the seed as a project-generated transformation: descriptions are
  omitted, fields are normalized, parent codes and source order are derived,
  and project metadata/checksums are added.
- Retain the exact source URL, retrieval date, raw SHA-256, official release,
  official counts, and generated content hash.
- Do not infer HSIC-to-ISIC Rev.5 mappings from HSIC's ISIC Rev.4 lineage.
- Rebuild only through the deterministic import command and require an explicit
  reviewed source artifact; runtime and startup never fetch C&SD or publish a
  revision automatically.
