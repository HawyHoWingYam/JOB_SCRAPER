# Company-industry taxonomy standards (Hong Kong job scraper)

Research date: 2026-07-18. Sources are official owners/statistical authorities.

## Scope boundary

Industry classifications describe economic activity; occupation classifications describe work performed by a person. The UN separates ISIC (economic activities) from ISCO (occupations): <https://unstats.un.org/unsd/classifications/Econ> and <https://unstats.un.org/unsd/classifications/Family>. ISCO/SOC therefore belong in a separate job-function dimension, not the company-industry taxonomy.

## Official candidates

### Hong Kong Standard Industrial Classification (HSIC) Version 2.0

Hong Kong Census and Statistics Department (C&SD) publishes HSIC as Hong Kong's economic-activity classification: <https://www.censtatd.gov.hk/en/page_698.html>. C&SD states that the current HSIC V2.0 has been used since 2009, is adapted from ISIC Rev.4 for Hong Kong's economy, and has five levels: Section, Division, Group, Class, and Sub-class. The same official page links the searchable structure, explanatory manual, and V1.1↔V2.0 concordance. It is the strongest geographic fit for Hong Kong. Seed labels/codes from the C&SD release, retain `HSIC V2.0` and source URL, and use C&SD correspondence tables for legacy mappings. C&SD publication copyright/permission terms govern redistribution.

### UN ISIC

ISIC is the UN Statistics Division's International Standard Industrial Classification of All Economic Activities. The UN portal states that the Statistical Commission endorsed **ISIC Rev.5 in 2023** and provides its 2024 introduction, explanatory notes, and machine-readable structure: <https://unstats.un.org/unsd/classifications/Econ/ISIC>. Rev.4 remains important because current HSIC V2.0 explicitly derives from it; Rev.4 structure and notes remain at <https://unstats.un.org/unsd/publication/seriesm/seriesm_4rev4e.pdf>. ISIC is internationally comparable but less Hong Kong-specific. Keep the exact revision and original code; mappings can be many-to-many and an HSIC↔ISIC Rev.5 relationship must not be inferred from the older HSIC↔Rev.4 lineage. Follow UN publication copyright terms.

### NAICS 2022

US Census/OMB publish NAICS 2022 files, manuals and 2017↔2022 concordances: <https://www.census.gov/naics/> and <https://www.whitehouse.gov/omb/information-for-agencies/naics/>. NAICS covers US-Canada-Mexico, not Hong Kong; revisions follow a five-year cycle. Use only for North American feeds, preserving country variant and year. No official HSIC crosswalk is supplied on these portals.

### NACE Rev. 2.1

Eurostat describes NACE as the EU economic-activity classification and states Rev. 2.1 implementation begins for reference year 2025: <https://ec.europa.eu/eurostat/web/nace>. EU scope makes it a regional alternative, not a Hong Kong seed. Preserve revision and any national extension; use Eurostat correspondence tables for mappings.

### GICS

GICS is maintained by S&P Dow Jones Indices and MSCI for equity-market analysis: <https://www.msci.com/our-solutions/indexes/gics> and <https://www.spglobal.com/spdji/en/landing/topic/gics/>. It is not a general economic-activity census classification. Methodology/data are proprietary and licensed; unsuitable as the freely redistributable primary taxonomy.

## Comparison and implementation implications

- **Fit and granularity:** HSIC is Hong Kong-specific; ISIC is global; NAICS/NACE are regional; GICS is market-sector oriented. HSIC/ISIC/NACE/NAICS provide hierarchical activity levels suitable for broad-to-specific company filters.
- **Stability/versioning:** Every assignment must carry standard and release. NAICS is explicitly five-yearly; NACE Rev.2.1 starts 2025; current HSIC V2.0 has been used since 2009; ISIC Rev.5 was endorsed in 2023. Use append-only snapshots with `valid_from`/`valid_to`; never overwrite historical codes.
- **Crosswalks:** C&SD, UN, Census and Eurostat publish correspondence/concordance material. Crosswalks may be many-to-many; retain provenance, method and confidence.
- **Labels/language:** Treat C&SD's release as authority for Chinese/English HSIC labels. Other owner releases are principally English (national variants may add languages); store original labels and source URL.
- **Licensing:** Government classifications remain subject to each owner's copyright/terms. GICS requires commercial licensing; do not copy proprietary content into an open taxonomy.

## Recommendation (inference)

Seed a project-owned **Company Industry Taxonomy** from the current **HSIC Version 2.0**, retaining its five-level hierarchy and bilingual labels. Add optional, explicitly revisioned ISIC codes only through a published or project-validated crosswalk; do not treat HSIC's Rev.4 lineage as an automatic Rev.5 mapping. Keep occupations/job functions (ISCO/SOC) separate. Use immutable records: `taxonomy_id`, `standard`, `release`, `code`, `parent_code`, `label_en`, `label_zh`, `source_url`, `valid_from`, `valid_to`, and mapping provenance/confidence. Version releases append-only and preserve many-to-many crosswalk edges.
