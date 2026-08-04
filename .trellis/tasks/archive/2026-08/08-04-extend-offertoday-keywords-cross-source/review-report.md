# OfferToday Keyword Pack cross-source review

**Verdict: INSUFFICIENT — retain the prior proposal and review supported cross-source additions.**

This follow-up is read-only. JobsDB and CTGoodJobs are discovery evidence; OfferToday remains the recommendation authority.

## Corpus scope

| Source | IT root | Usable details | Included IT details | Excluded without root | Date range |
| --- | --- | ---: | ---: | ---: | --- |
| ctgoodjobs | ctgoodjobs:021 | 3,178 | 3,178 | 0 | 2026-06-22T00:00:00 to 2026-07-29T00:00:00 |
| jobsdb | jobsdb:6281 | 3,565 | 3,559 | 6 | 2025-05-19T02:45:53.611000 to 2026-07-28T09:56:37.406000 |
| offertoday | offertoday:118000 | 1,139 | 1,139 | 0 | 2026-05-05T00:00:00 to 2026-07-30T00:00:00 |

### Title language distribution

| Source | Latin | Mixed | Chinese | Other |
| --- | ---: | ---: | ---: | ---: |
| ctgoodjobs | 3,051 | 99 | 28 | 0 |
| jobsdb | 3,431 | 87 | 41 | 0 |
| offertoday | 727 | 202 | 210 | 0 |

## Limitations

- Cross-source frequency is discovery evidence, not OfferToday query recall or precision.
- JobsDB and CTGoodJobs date, language, taxonomy, and collection routes differ.
- Description matches may name a tool dependency rather than the hiring role.
- The archived OfferToday probe and any fresh candidate probe are temporally different bounded samples.
- Fresh candidate IDs are compared with an earlier archived bounded sample.
- Ranking and inventory may have changed between probe timestamps.
- A bounded new-ID count is not full-source recall or precision.

## Candidate evidence and disposition

| Candidate | Scope | JobsDB title/detail | CTGoodJobs title/detail | OfferToday title/detail | Final disposition | Risk |
| --- | --- | ---: | ---: | ---: | --- | --- |
| AI | new | 308/1,020 | 259/933 | 70/193 | rejected_noise | Already present and too broad for a new change |
| Confluence | new | 1/74 | 0/76 | 0/40 | needs_offertoday_evidence | Broad tool dependency across many roles |
| data warehouse | new | 3/57 | 0/47 | 1/8 | rejected_noise | Broad and duplicate-heavy |
| Databricks | new | 4/78 | 3/52 | 0/11 | supported_addition | May overlap Spark and data engineer queries |
| Dynamics 365 | new | 5/27 | 2/30 | 0/4 | variant_or_replacement | Semantic overlap with current Dynamics term |
| Fortinet | new | 0/42 | 0/21 | 1/19 | needs_offertoday_evidence | Description-only support and vendor overlap |
| information security | new | 18/160 | 15/99 | 2/6 | rejected_noise | Too broad and highly redundant |
| ISO 27001 | new | 0/72 | 0/43 | 0/7 | needs_offertoday_evidence | Description-only compliance evidence |
| ITIL | new | 0/170 | 0/122 | 0/30 | needs_offertoday_evidence | Certification requirement may not define the role |
| Jira | new | 1/174 | 0/142 | 0/64 | needs_offertoday_evidence | Broad tool dependency across many roles |
| Microsoft 365 | new | 1/97 | 0/75 | 0/23 | needs_offertoday_evidence | Semantic overlap with prior Microsoft candidate |
| penetration testing | new | 2/36 | 0/26 | 0/0 | variant_or_replacement | Overlap with cybersecurity and security testing |
| Power Automate | new | 0/46 | 0/25 | 0/6 | needs_offertoday_evidence | Description-only support and Microsoft overlap |
| RPA | new | 8/45 | 3/16 | 1/4 | supported_addition | Acronym may appear outside hands-on engineering roles |
| Snowflake | new | 0/31 | 0/32 | 0/2 | needs_offertoday_evidence | Description-only support may not improve title recall |
| Splunk | new | 1/21 | 3/16 | 0/6 | needs_offertoday_evidence | Crosses operations and security roles |
| Spring Boot | new | 1/143 | 0/88 | 1/31 | supported_addition | May overlap Java and Spring queries |
| Tableau | new | 1/79 | 0/76 | 1/14 | supported_addition | Often appears only as a tool dependency |
| TOGAF | new | 0/16 | 0/18 | 0/3 | needs_offertoday_evidence | Description-only certification evidence |
| VMware | new | 2/136 | 2/75 | 0/54 | supported_addition | Vendor mention may be a secondary skill |
| AIGC | prior_addition | 0/3 | 1/5 | 11/18 | prior_addition_revalidated | Acronym context can vary |
| CRM | prior_addition | 10/118 | 8/95 | 4/31 | prior_addition_revalidated | Broad enterprise context |
| Helpdesk | prior_addition | 27/98 | 21/53 | 10/22 | prior_addition_revalidated | Overlap with support |
| Microsoft | prior_addition | 16/457 | 4/438 | 3/118 | prior_addition_revalidated | Vendor mention may not define the role |
| Oracle | prior_addition | 17/260 | 15/192 | 9/87 | prior_addition_revalidated | Vendor mention may not define the role |
| UAT | prior_addition | 12/404 | 3/316 | 11/74 | prior_addition_revalidated | May overlap testing and business analyst terms |
| 前端开发工程师 | prior_addition | 1/1 | 0/0 | 9/9 | prior_addition_revalidated | Overlap with English frontend terms |
| 技术支持 | prior_addition | 0/7 | 0/2 | 4/16 | prior_addition_revalidated | Overlap with support variants |
| 技術支援 | prior_addition | 3/11 | 3/12 | 14/59 | prior_addition_revalidated | Overlap with support variants |
| 桌面運維 | prior_addition | 0/1 | 0/0 | 17/20 | prior_addition_revalidated | Overlap with desktop support |
| 網絡工程師 | prior_addition | 0/1 | 0/0 | 10/10 | prior_addition_revalidated | Overlap with network engineer |
| 軟件工程師 | prior_addition | 1/4 | 0/1 | 7/8 | prior_addition_revalidated | Overlap with software engineer variants |
| 软件工程师 | prior_addition | 0/1 | 0/0 | 5/7 | prior_addition_revalidated | Overlap with software engineer variants |
| 运维工程师 | prior_addition | 0/0 | 0/0 | 17/17 | prior_addition_revalidated | Overlap with operations terms |
| 駐場工程師 | prior_addition | 0/0 | 0/0 | 11/11 | prior_addition_revalidated | May cross into non-IT field engineering |
| angular | prior_deferred | 1/55 | 0/28 | 1/6 | retain | Framework demand can vary by source and time |
| pentest | prior_retirement | 1/1 | 0/0 | 0/0 | retire_candidate | Source terminology may prefer the full phrase |

### Representative Job Details

#### `AI`

- jobsdb: `86640084` — AI Project Manager - Top-Tier Insurer - Up to HK$73K (title)
- jobsdb: `88689154` — Business Analys, AI Chatbot, Insurance (6m contract renew) (title)
- ctgoodjobs: `10156871` — AI Engineer \| Bank (title)
- ctgoodjobs: `10156969` — AI Engineer \| Bank (title)
- offertoday: `01ueWbWJQa94EJcKQ7uiyg==` — Senior AI Engineer - IDP(Intelligent Document Processing) (title)
- offertoday: `0aXN-XME18TS9CqU0z2-xg==` — AI Engineer (title)

#### `Confluence`

- jobsdb: `92998741` — Digital Business Analyst (Jira, Confluence) (title)
- jobsdb: `86530382` — IT Digital Project Manager/ Scrum Master  - 60k (Insurance) (description)
- ctgoodjobs: `10156941` — Digital Business Analyst, Banking - Up to $35k (description)
- ctgoodjobs: `10156979` — Lead Digital Business Analyst, Banking/Investment (description)
- offertoday: `0vRBanB0qbPs9Jo0X-lnAA==` — IT Manager – Digital Transformation & Business Analysis (description)
- offertoday: `1TYYLzONgpq60jhxB3sfzw==` — IT Project Manager (description)

#### `data warehouse`

- jobsdb: `93165775` — Data Warehouse Engineer (title)
- jobsdb: `93346858` — Data Warehouse & BI:  System Analyst / Analyst Programmer - Major Bank (title)
- ctgoodjobs: `10156997` — BI Specialist / Data Analyst (Five day work weeks) (description)
- ctgoodjobs: `10157125` — Assistant Manager, Data & Business Intelligence/ System Analyst ( Urgent ) (description)
- offertoday: `4vaJXPCISukmKxQNgyEP3Q==` — Data Warehouse Engineer (title)
- offertoday: `8H-UsA50angN4r3iZd9nGw==` — Data / Database Architect (HK$50K - $70K+) (Ref. No.: 27696) (description)

#### `Databricks`

- jobsdb: `93007599` — Business Analyst - Data Engineer (Databricks \| Fabric \| Power BI) (title)
- jobsdb: `93138938` — Data System Analyst x 2 (Pyspark/Databricks, 45K~) (title)
- ctgoodjobs: `10175355` — DataBricks Data Analytics Consultant (title)
- ctgoodjobs: `10178598` — Data Engineer (Azure & Databricks) (title)
- offertoday: `57Sr3ITIfXqRFSBTCRgffg==` — Senior Data Engineer (description)
- offertoday: `CrGMVGtQEbULF_KO3NjHsQ==` — 大型金融公司 講完個名你一定知請Senior Manager - Data Management, Digitalisation Office) (description)

#### `Dynamics 365`

- jobsdb: `92993324` — ERP Consultant - Microsoft Dynamics 365 (title)
- jobsdb: `93148171` — Systems Analyst (Microsoft Dynamics 365 CRM) (title)
- ctgoodjobs: `10197441` — Senior Dynamics 365 Business Central Consultant (title)
- ctgoodjobs: `10198041` — Manager - Transformation Advisory (Microsoft Dynamics 365 ERP) (title)
- offertoday: `XhzGBeB_p_gP5s3tNE0uMQ==` — Marketo Marketing Automation Specialist (description)
- offertoday: `gyzH_aN8u4ujJKmZo7FPzQ==` — Global IT Infrastructure (APAC) 50K - 70K (description)

#### `Fortinet`

- jobsdb: `87236917` — Network Engineer (description)
- jobsdb: `92899670` — INFRASTRUCTURE SPECIALIST (description)
- ctgoodjobs: `10159975` — Network Security Engineer- Leading Financial Firm- 50k+ (description)
- ctgoodjobs: `10164682` — HK Network Security Engineer (Firewall) (description)
- offertoday: `lSaTqlk5d1dn-B8U3AV4Yg==` — Engineer (NOC) (Cisco / Fortinet) (SRC260306) (title)
- offertoday: `10ZsDccTeSVZ_WPwB1hPfw==` — Senior System Administrator(IT Security) (description)

#### `information security`

- jobsdb: `93062227` — Associate - Information Security Governance - IT (title)
- jobsdb: `93451892` — Information Security Manager (title)
- ctgoodjobs: `10162746` — Information Security Manager (title)
- ctgoodjobs: `10172209` — Senior Information Security Analyst (at the rank of Senior Officer) (Post Ref.: 26/185) (title)
- offertoday: `LIhQYZ2_JrjVQJVta0qGBw==` — IT和信息安全经理-Infra and Information Security Manager (title)
- offertoday: `co6sSx7tcZR8MhZIhBBVVw==` — Information Security Specialist (title)

#### `ISO 27001`

- jobsdb: `92985325` — Senior Consultant - Cybersecurity (description)
- jobsdb: `93252248` — Senior Consultant - Cybersecurity (description)
- ctgoodjobs: `10159569` — Senior Technology Risk Manager /Technology Risk Manager (Cyber Security Control (description)
- ctgoodjobs: `10159909` — Senior Technology Risk Manager /Technology Risk Manager (Cyber Security Control Division) (description)
- offertoday: `LIhQYZ2_JrjVQJVta0qGBw==` — IT和信息安全经理-Infra and Information Security Manager (description)
- offertoday: `ZUdLqMccBiXTsp9l4_PhaA==` — Cloud Engineer （UP TO 55K！） (description)

#### `ITIL`

- jobsdb: `74668527` — System Administrator (description)
- jobsdb: `93067418` — Application Support Engineer (description)
- ctgoodjobs: `10157030` — IT Engineer - International School (IMMEDIATE) (description)
- ctgoodjobs: `10157070` — IT Infrastructure Team - Network and Systems ( 3 x Openings) (description)
- offertoday: `-XeruXR7PXpnpACp_LTJgQ==` — Head of Technical Service Delivery (Data Security) (description)
- offertoday: `0UG2Hwd8ePUplVzvJSPxCw==` — 智慧項目交付經理 (description)

#### `Jira`

- jobsdb: `92998741` — Digital Business Analyst (Jira, Confluence) (title)
- jobsdb: `86154847` — QA Test Engineer (Cloud platform), 45k (description)
- ctgoodjobs: `10156941` — Digital Business Analyst, Banking - Up to $35k (description)
- ctgoodjobs: `10156979` — Lead Digital Business Analyst, Banking/Investment (description)
- offertoday: `0vRBanB0qbPs9Jo0X-lnAA==` — IT Manager – Digital Transformation & Business Analysis (description)
- offertoday: `1TYYLzONgpq60jhxB3sfzw==` — IT Project Manager (description)

#### `Microsoft 365`

- jobsdb: `93372938` — IT Support Officer (Helpdesk + Microsoft 365 / Office Suite) (title)
- jobsdb: `91487806` — Information Technology Support Engineer (description)
- ctgoodjobs: `10157147` — System Consultant (description)
- ctgoodjobs: `10160937` — IT Manager (description)
- offertoday: `5LsVZ_cNqcShZCoRjZvdAQ==` — Azure Cloud System Engineer  雲端系統工程師 (description)
- offertoday: `8JC6U6c0YOEW-veycxs9GA==` — AI Engineer( Microsoft Copilot) (description)

#### `penetration testing`

- jobsdb: `92900056` — Senior Manager - Operational Technology Penetration Testing (title)
- jobsdb: `90552968` — Consultant/Senior Consultant, Cyber Security (Penetration Testing/Red Teaming) (title)
- ctgoodjobs: `10160852` — Cybersecurity Lead (Banking 1-1.2M) (description)
- ctgoodjobs: `10162536` — IT Infrastructure and Security Manager (description)

#### `Power Automate`

- jobsdb: `91056215` — Cybersecurity and Network and Firewall SME (description)
- jobsdb: `89802597` — Full‑Stack Developer (CRM & Power Platform) - Insurance (description)
- ctgoodjobs: `10160285` — Cybersecurity and Vulnerability Analyst - 30-40k (description)
- ctgoodjobs: `10163254` — Technical Business Analyst (description)
- offertoday: `8JC6U6c0YOEW-veycxs9GA==` — AI Engineer( Microsoft Copilot) (description)
- offertoday: `KbA-HZeCtHgpnIyRd4UfMw==` — AI Engineer (description)

#### `RPA`

- jobsdb: `93004314` — RPA Developer (UiPath) (title)
- jobsdb: `93176997` — Automation Analyst(RPA, AI, python),  Data Engineer (Python, Spark, AWS) (title)
- ctgoodjobs: `10170422` — Business Technology Manager / Business Analyst – RPA (title)
- ctgoodjobs: `10193746` — Automation Analyst - RPA & AI (Junior - Senior grade) (title)
- offertoday: `NBwH8GklChF5gJ3A3uoXug==` — RPA Engineer (Python) - FinTech / AI / Enterprise Automation (title)
- offertoday: `sVmXFDU2ONHBrbjNb8VAsw==` — IT Business Analyst (description)

#### `Snowflake`

- jobsdb: `91056113` — Data Engineer (description)
- jobsdb: `91056443` — BI Developer (SSAS / Power BI) (description)
- ctgoodjobs: `10156982` — Data Engineer (description)
- ctgoodjobs: `10159994` — Senior Data Engineer (GenAI) (description)
- offertoday: `fF48cNyy_1bH3TUGT-eowA==` — Data Platform Engineer (description)
- offertoday: `HmSFpC0q2gDDeBXU6dUb8g==` — Senior Data Developer (description)

#### `Splunk`

- jobsdb: `92900550` — Splunk Area Technical Account Manager (title)
- jobsdb: `74668527` — System Administrator (description)
- ctgoodjobs: `10161149` — Splunk Area Technical Account Manager (title)
- ctgoodjobs: `10161183` — Splunk Area Technical Account Manager (title)
- offertoday: `66iyhwS9mH-bL0Jf5a4zmg==` — 安全SOC工程师(Remote) (description)
- offertoday: `DX6zye-VXX3r5VUd8eJvdQ==` — 安全SOC工程师(Remote) (description)

#### `Spring Boot`

- jobsdb: `89980817` — System Analyst (JAVA Spring Boot, HKD 55K) (title)
- jobsdb: `78526747` — Assistant Digital Engineer, Back End (description)
- ctgoodjobs: `10156888` — Front-end/Back-end developer (description)
- ctgoodjobs: `10157102` — Front-end/Back-end developer (description)
- offertoday: `XDJzpgl53aTwTAeDfGvmOA==` — Backend Developer, Java Spring Boot/Golang/Node.js (title)
- offertoday: `3fhHPHd5eDK9MHr2H3Vrrg==` — Java Developer (Programmer/Analyst Programmer/System Analyst) (description)

#### `Tableau`

- jobsdb: `93174294` —  ETL Developer (Asset Management, SQL, Python, Tableau) (title)
- jobsdb: `91056443` — BI Developer (SSAS / Power BI) (description)
- ctgoodjobs: `10156997` — BI Specialist / Data Analyst (Five day work weeks) (description)
- ctgoodjobs: `10157729` — Data Engineer (description)
- offertoday: `SVZ54TOzBOJCiZepz0UL8g==` — Tableau Developer (title)
- offertoday: `0j8uE-5xSntYjYjZhgCNDw==` — Data Analyst/ AI Engineer (description)

#### `TOGAF`

- jobsdb: `90816413` — Utility Architect – Hong Kong (description)
- jobsdb: `93251700` — Associate Solutions Architect (Insurance) (description)
- ctgoodjobs: `10162370` — Associate Solution Architect (Insurance) - Renewable 6-month contract (description)
- ctgoodjobs: `10166801` — Associate Solution Architect (Insurance) - Renewable 6-month contract (description)
- offertoday: `PcMddaiqpYUthSdy3VXmYQ==` — IT Infrastructure Architect (description)
- offertoday: `oUFHBWcEsfIWEBSOz8FNyA==` — Data and Artificial Intelligence Architect (description)

#### `VMware`

- jobsdb: `93214710` — System Administrator (VMware/Wintel) (title)
- jobsdb: `93227303` — System Administrator (VMware) (title)
- ctgoodjobs: `10180912` — System Engineer (Windows, VMWare, SAN) (title)
- ctgoodjobs: `10181161` — Senior Infrastructure Engineer (VMware, Windows, Databases) (SI) (title)
- offertoday: `0ae2CNWKAeN-Wz9SstFooQ==` — System Administrator (description)
- offertoday: `0zhKPge7qOvY1-GZcnLISQ==` — Regional IT Manager (ERP & Infrastructure) 55K - 80K (description)

#### `AIGC`

- jobsdb: `93375101` — Binance Accelerator Program - Product Manager AI Agent & Harness (description)
- jobsdb: `93375104` — Product Manager, AI Agent & Harness (description)
- ctgoodjobs: `10190813` — QA Engineer（AIGC） (title)
- ctgoodjobs: `10167144` — Senior Staff / Principal AI Engineer, Computer Vision (description)
- offertoday: `CA3DEk6rUqsoTweD1vThvg==` — AIGC Data Operations Specialist (title)
- offertoday: `GILm8bVgUD1DlO71bw8BLg==` — AIGC Data Operations Specialist (title)

#### `CRM`

- jobsdb: `89802597` — Full‑Stack Developer (CRM & Power Platform) - Insurance (title)
- jobsdb: `92391420` — CRM Sr Advisory Solution Consultant, Hong Kong (title)
- ctgoodjobs: `10161335` — CRM- Senior / Data Analyst (title)
- ctgoodjobs: `10163288` — Manager, Data Analytics & CRM (AI Product Manager) 45-55k (title)
- offertoday: `rP3mVho30iOSNert4nHGhw==` — CRM Developer  / Analyst Programmer (title)
- offertoday: `2ps-IXNaBxI5GKmhtgpXFA==` — CRM Developer - Java, AI,  ($33-$35K x 13 \| Whampoa) (title)

#### `Helpdesk`

- jobsdb: `92907861` — IT Helpdesk/ Operator (Ref: CC/MSI/HD) (title)
- jobsdb: `92916575` — Customer Service Executive (General IT Helpdesk) (無IT經驗亦可申請) (7 x 24) (title)
- ctgoodjobs: `10157451` — Helpdesk Engineer (title)
- ctgoodjobs: `10159497` — Technical Support Engineer (Business Service Helpdesk) (title)
- offertoday: `4znppM2ej1iiKHYzmjpikA==` — Contract System Administrator x3 (Helpdesk/Network/Cloud) (HK$25K - $50K) (title)
- offertoday: `J_miKYBaIkhLXYY1tgK30A==` — Helpdesk Engineer/Support - Leading Investment Bank (title)

#### `Microsoft`

- jobsdb: `92993324` — ERP Consultant - Microsoft Dynamics 365 (title)
- jobsdb: `93011427` — ERP Functional Consultant – Microsoft Dynamics (title)
- ctgoodjobs: `10185187` — Senior Data Engineer (Microsoft Fabric / Lakehouse) (title)
- ctgoodjobs: `10188007` — Microsoft Solutions - Enterprise Architect – In-House Perm Role - MNC (title)
- offertoday: `8JC6U6c0YOEW-veycxs9GA==` — AI Engineer( Microsoft Copilot) (title)
- offertoday: `glrfbudEoUY-3NG1DHkjuw==` — Cloud Architect/ Senior Consultant (Microsoft Azure) (title)

#### `Oracle`

- jobsdb: `89779527` — (Senior) Specialist - Oracle Cloud (title)
- jobsdb: `92919298` — Data Engineer (ETL/Oracle/UNIX, over $40K) (title)
- ctgoodjobs: `10162643` — Technology - Oracle Solution Architect/ Deployment Lead (title)
- ctgoodjobs: `10171255` — System Analyst (Oracle & Java) (title)
- offertoday: `HpZ6i9JISW6hy0KGf4op0w==` — Oracle Cloud Engineer (OCI / Fusion / PaaS) (title)
- offertoday: `JTKnRRVN4_iyAe9nmvP_gg==` — Oracle Cloud Engineer-contractor (title)

#### `UAT`

- jobsdb: `92995051` — UAT Tester (Welcome Fresh Graduate) (title)
- jobsdb: `93000455` — (Bank / IT) Business Analyst /Project Management/ UAT (title)
- ctgoodjobs: `10186750` — Project Officer / Business Analyst / UAT Tester (Banking services) (title)
- ctgoodjobs: `10189315` — Major Bank: UAT Testers (title)
- offertoday: `P7xng-tOCYyJdaszpCi0iw==` — UAT Tester (Urgent) (title)
- offertoday: `_SL_vP1mB2C3wmusu3AgWg==` — (Digital Banking) Business Analyst /UAT/Project Management/ Fresh graduate (title)

#### `前端开发工程师`

- jobsdb: `93077879` — 前端开发工程师（移动端 / Web端） (title)
- offertoday: `0k4FB2T8185dP-F65EtDkg==` — 前端开发工程师 (title)
- offertoday: `16OcpPXGy3F6qcAPwtxuKg==` — 前端开发工程师 (title)

#### `技术支持`

- jobsdb: `89483701` — AVP - Testing Engineer - IT (description)
- jobsdb: `93098474` — 网络运维 (description)
- ctgoodjobs: `10178336` — IT Engineer (description)
- ctgoodjobs: `10195151` — 量化开发师 (description)
- offertoday: `FHfyBbFW8SABqLx9UXSjCw==` — 技术支持 (title)
- offertoday: `BGr5jAvTgaPzsbdkjRfWfQ==` — 技术支持 (title)

#### `技術支援`

- jobsdb: `93119119` — 資訊科技助理 / 學校技術支援服務員 TSS (合約) (title)
- jobsdb: `93109392` — 技術支援助理 Technical Support Specialist (title)
- ctgoodjobs: `10181243` — 資訊科技技術支援人員(TSS) (title)
- ctgoodjobs: `10181319` — 資訊科技技術支援人員 (title)
- offertoday: `3n33EQCvJqOVogNGY5PAkQ==` — 桌面運維／技術支援（駐場工程師｜初級） (title)
- offertoday: `ECMdmej4TC2KRVrzQ-B_ww==` — 技術支援員 (title)

#### `桌面運維`

- jobsdb: `93072617` — IT Endpoint Digital Operations Opening (description)
- offertoday: `3n33EQCvJqOVogNGY5PAkQ==` — 桌面運維／技術支援（駐場工程師｜初級） (title)
- offertoday: `EkEsC60iOEqnnMZp5PJd8Q==` — 桌面運維／技術支援（駐場工程師｜初級） (title)

#### `網絡工程師`

- jobsdb: `93072617` — IT Endpoint Digital Operations Opening (description)
- offertoday: `DxyVI0QiVqyshHlrrgPJdQ==` — 網絡工程師 (title)
- offertoday: `ECbsHN5sgLkluzzVyu0FEg==` — 網絡工程師 (title)

#### `軟件工程師`

- jobsdb: `92977312` — Software Engineer 軟件工程師 (title)
- jobsdb: `93122669` — Assistant Data & Business Intelligence Manager/System Analyst/Web Programmer (description)
- ctgoodjobs: `10174177` — Assistant Data & Business Intelligence Manager/System Analyst/Web Programmer (description)
- offertoday: `ASix46Vzx5fuVt5cbfaciA==` — Frontend Developer 軟件工程師 (系統) (5 days) (title)
- offertoday: `CSKCESNZQnBBwCjR4fJU2Q==` — 軟件工程師 (title)

#### `软件工程师`

- jobsdb: `93260066` — Intermediate/Senior Ultrasound Application Software Engineer (description)
- offertoday: `b8CDAYwcvveGyw_Legur1g==` — 嵌入式软件工程师 (title)
- offertoday: `bJprZOg7FTnITzjWkjJgTg==` — 软件工程师（中级） (title)

#### `运维工程师`

- offertoday: `ERG_WU-I8rKTXbZ32RbB0A==` — Avaya语音系统运维工程师 (title)
- offertoday: `GY2eQGRMj4QaBHkyjmKdAg==` — 视频会议运维工程师 (title)

#### `駐場工程師`

- offertoday: `3n33EQCvJqOVogNGY5PAkQ==` — 桌面運維／技術支援（駐場工程師｜初級） (title)
- offertoday: `EkEsC60iOEqnnMZp5PJd8Q==` — 桌面運維／技術支援（駐場工程師｜初級） (title)

#### `angular`

- jobsdb: `92918365` — Senior / Analyst Programmer (C# .NET/Angular, $35K - $46K) (title)
- jobsdb: `86154846` — Junior Full Stack Developer (1-3 years experience) (description)
- ctgoodjobs: `10157478` — Binance Accelerator Program - Frontend Engineer (.COM) (description)
- ctgoodjobs: `10159758` — Software Engineer (RAD, Prime Finance) (description)
- offertoday: `yNyVaEn6bWR_G81R9Fg9zQ==` — Angular Developer (title)
- offertoday: `95PzZzREepDnbnv3lIdagA==` — 前端开发工程师 (description)

#### `pentest`

- jobsdb: `93293128` — Consulting - Cyber Security - Pentest - Staff/Senior - Hong Kong (title)


## Fresh OfferToday probe

- Status: `complete`
- Listing API requests: 16 / 60
- Archived baseline finished at: `2026-08-04T12:10:30.692849+00:00`
- Fresh probe finished at: `2026-08-04T14:09:26.182226+00:00`

| Candidate | Observed rows | Distinct IDs | New vs archived current pack | Decision |
| --- | ---: | ---: | ---: | --- |
| Databricks | 22 | 20 | 9 | supported_addition |
| Dynamics 365 | 22 | 20 | 8 | supported_addition |
| RPA | 22 | 20 | 12 | supported_addition |
| Splunk | 22 | 0 | 0 | needs_offertoday_evidence |
| Spring Boot | 22 | 20 | 8 | supported_addition |
| Tableau | 22 | 20 | 18 | supported_addition |
| VMware | 22 | 20 | 13 | supported_addition |
| penetration testing | 22 | 20 | 8 | supported_addition |

## Recommendations

- Newly supported additions: `Databricks`, `RPA`, `Spring Boot`, `Tableau`, `VMware`
- Prior additions revalidated: `AIGC`, `CRM`, `Helpdesk`, `Microsoft`, `Oracle`, `UAT`, `前端开发工程师`, `技术支持`, `技術支援`, `桌面運維`, `網絡工程師`, `軟件工程師`, `软件工程师`, `运维工程师`, `駐場工程師`
- Variants or replacements: `Dynamics 365`, `penetration testing`
- Retire candidates: `pentest`
- Retain/defer: `angular`

No catalog mutation is performed. Accepted changes must use a separate CSV preview/confirm workflow.

