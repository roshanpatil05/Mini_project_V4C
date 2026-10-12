# Current Repository Architecture

## 1. PROJECT SUMMARY

This is a Python employee analytics application that scales the IBM HR Analytics dataset into reproducible employee, project, assignment, review, and SCD Type 2 CSV data, loads it into MySQL, and serves analytics through Streamlit. It uses pandas, NumPy, Faker, KaggleHub, PyMySQL, Plotly, and Streamlit. It is run with `python -m src.ETL.synthesizer`, `python -m src.run_etl`, and `streamlit run src/streamlit_app.py`; Streamlit Cloud deployment is documented but has no repository deployment configuration.

## 2. LAYER-BY-LAYER INVENTORY

### a) Data sources

- `src/data/synthetic_employees.csv`: generated employee snapshot; currently 120,000 employee rows in the committed dataset.
- `src/data/employee_scd2_history.csv`: generated employee department/job/salary versions with `start_date`, `end_date`, and `is_current`.
- `src/data/synthetic_performance_reviews.csv`: generated review ID, employee ID, review date, score, rating, and comments.
- `src/data/synthetic_projects.csv`: generated 500 projects.
- `src/data/synthetic_project_assignments.csv`: generated project assignments with roles, allocation percentages, and assignment dates.
- IBM HR Analytics Attrition dataset: downloaded at runtime by `kagglehub` in `DataSynthesizer.download_ibm_data()`.
- `.env` or shell environment variables: external database configuration loaded by `src/config/settings.py`.
- MySQL server: external runtime database configured through `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME`.

### b) Data synthesis / generation

- `src/ETL/synthesizer.py`: `DataSynthesizer` uses KaggleHub, Faker, NumPy, and pandas.
- Default configuration: 120,000 employees, 30% historical fraction, seed `42`.
- Methods: `download_ibm_data()`, `generate_base_employee_data()`, `generate_projects()`, `generate_project_assignments()`, `generate_scd_type_2_history()`, `generate_performance_reviews()`, and `export_to_csv()`.
- Outputs: `synthetic_employees.csv`, `employee_scd2_history.csv`, `synthetic_performance_reviews.csv`, `synthetic_projects.csv`, and `synthetic_project_assignments.csv` under `src/data/`.
- `src/ETL/extractor.py`: `CSVExtractor.extract()` reads CSVs and parses recognized date columns.
- `src/ETL/transformer.py`: `DataTransformer.build_employee_history()` merges identity fields and validates employee IDs, one current version per employee, and date intervals.

### c) Ingestion / staging load

- `src/run_etl.py`: command-line entry point for `DataWarehouseLoader`.
- `src/ETL/loader.py`: `DataWarehouseLoader`, inheriting from `DatabaseConnection`, reads CSVs directly and loads MySQL in batches of 1,000.
- Load order: extract employee/history data; validate SCD2 data; load departments; optionally load projects; load employees; optionally load assignments and reviews; load employee versions; call warehouse ETL procedures.
- No physical staging/Bronze database or staging tables exist. CSV files are the pre-load layer.

### d) OLTP database

- Database: `employee_analytics`, defined in `src/database/schema.sql`.

- `departments`: PK `department_id`; unique `department_name`.
- `employees`: PK `employee_id`; FKs `department_id -> departments.department_id`, `manager_id -> employees.employee_id`; names, email, job title, hire date, salary, performance score, attrition risk, status.
- `projects`: PK `project_id`; FK `department_id -> departments.department_id`; project name, budget, dates, status.
- `project_assignments`: PK `assignment_id`; FKs `employee_id -> employees.employee_id`, `project_id -> projects.project_id`; unique `(employee_id, project_id)`; allocation percentage and assigned date.
- `performance_reviews`: PK `review_id`; FKs `employee_id -> employees.employee_id`, `manager_id -> employees.employee_id`; review date, score, rating, comments.

### e) ETL

- Orchestration: `src/run_etl.py` and `src/ETL/loader.py`.
- Stored procedures in `src/database/schema.sql`: `sp_etl_dim_date()`, `sp_etl_dim_project()`, and `sp_etl_fact_reviews()` are called by `DataWarehouseLoader.load_review_facts()`; `sp_close_employee_scd2_version(p_employee_id, p_effective_date)` exists for closing a current `dim_employee` row but is not called by the Python runtime SCD2 path.
- Date load in `DataWarehouseLoader.load_review_facts()`: source `performance_reviews`, target `dim_date`, integer `YYYYMMDD` keys.
- Project load: source `projects`, `departments`, and `dim_department`; target `dim_project`.
- Fact load: source `performance_reviews`, `project_assignments`, `dim_employee`, and `dim_project`; target `fact_performance_reviews`.
- `ranked_assignments` CTE in `src/ETL/loader.py` uses `ROW_NUMBER() OVER (PARTITION BY pr.review_id ORDER BY pa.assigned_date DESC, pa.assignment_id DESC)` to select the latest eligible assignment.
- Fact loading resolves the employee SCD2 version with `review_date >= start_date` and `end_date IS NULL OR review_date < end_date`.
- `src/managers.py`: `AnalyticsManager.get_top_performers()` uses an `employee_scores` CTE and `DENSE_RANK() OVER (PARTITION BY department_name ORDER BY overall_score DESC)`.
- No database views are implemented.
- `EmployeeManager._apply_scd2_change()` directly closes the current dimension row, updates OLTP employee data, inserts a new current dimension row, and commits the transaction.

### f) OLAP data warehouse

The warehouse tables are in the same `employee_analytics` schema; no separate warehouse schema exists.

- `dim_department`: surrogate PK `department_key`; business key `department_id`; department name.
- `dim_employee`: surrogate PK `employee_key`; business key `employee_id`; FK `department_key`; SCD2 columns `start_date`, `end_date`, `is_current`; employee attributes, salary, performance score, and attrition risk.
- `dim_project`: surrogate PK `project_key`; business key `project_id`; FK `department_key`; project name.
- `dim_date`: PK `date_key`; unique `full_date`; year, quarter, month, and day attributes.
- `fact_performance_reviews`: surrogate PK `fact_review_key`; unique `review_id`; FKs `employee_key`, `department_key`, `project_key`, and `date_key`; measures/descriptors `overall_score`, `rating`, `review_date`, and `employee_id`.
- Diagram representation: `src/database/dimensional_model.mmd`.

### g) Backend application code

- `src/database/db_manager.py`: `DatabaseConnection` is a per-class singleton registry using `_instances`; it manages PyMySQL connections, execution, fetches, rollback, and close operations.
- `src/models.py`: dataclasses `Employee`, `Project`, and `Review` with validation methods.
- `src/managers.py`: all manager classes inherit from `DatabaseConnection`.
- `EmployeeManager`: `list_departments()`, `create_employee()`, `update_department()`, `update_salary()`, `_apply_scd2_change()`, and `list_employees()`; touches OLTP departments/employees and warehouse department/employee dimensions.
- `ProjectManager`: `create_project()`, `assign_employee()`, `get_project()`, `update_project()`, and `delete_project()`; touches `projects` and `project_assignments`.
- `ReviewManager`: `create_review()`; touches `performance_reviews`.
- `AnalyticsManager`: `get_performance_trends()`, `get_top_performers()`, `get_attrition_risk()`, `get_project_bottlenecks()`, and `get_overview_metrics()`; reads OLTP and OLAP tables.
- Database operations use exception handling, rollback, commit, and re-raise behavior.

### h) Streamlit frontend

- Entry point: `src/streamlit_app.py`.
- Shared presentation layer: `src/ui/theme.py` and `src/ui/__init__.py`; contains V4C color tokens, CSS, page headers, KPI cards, status badges, info pills, score bands, and Plotly styling.
- Overview: local CSV metrics, department count, MySQL/local status, average score, and employees-by-department chart; calls `EmployeeManager.list_departments()` for connectivity status.
- Employee Management: searches, updates, and deactivates employees; department and salary changes trigger SCD2 updates through `EmployeeManager`.
- Project Management: Create Project, Assign Employee, and Manage Projects tabs using `Project` and `ProjectManager`; writes to and updates `projects` and `project_assignments`.
- Performance Reviews: Create Review and Manage Reviews tabs using `Review` and `ReviewManager`; writes to and updates `performance_reviews`.
- Analytics Dashboard: calls `AnalyticsManager`; shows year-over-year review score, top performers, attrition risk, and project bottleneck/resource allocation analytics. The current UI fixes `department_basis` to `review` and uses a department filter; it no longer exposes the prior department-attribution radio toggle.
- Local fallback: `load_local_data()` and `local_analytics()` read the three CSV files when analytics queries are unavailable or empty. No local fallback exists for writes.

### i) Configuration and secrets

- `src/config/settings.py`: calls `load_dotenv()` and reads `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME` from Streamlit secrets first, then environment variables, with defaults.
- `.streamlit/config.toml`: Streamlit dark theme and V4C primary/background colors.
- `.gitignore`: ignores `.env`, virtual environments, and Python cache files.
- `st.secrets` is supported by `_get_secret()` for Streamlit Cloud; local `.env`/environment variables are the fallback.

### j) Version control and CI

- Visible branches: `main`, `Shraddha`, `roshan`; remotes include `origin/main`, `origin/Shraddha`, and `origin/roshan`.
- Recent commits include `fb6e961 Streamlit UI Updated` and `7fdbfa1 Updated code (#1)`.
- No `.github` directory or GitHub Actions workflows exist.
- No automated CI configuration is implemented.

### k) Deployment

- README specifies Python 3.10 or newer and MySQL 8.0 or newer.
- Dependencies are declared in `requirements.txt`.
- Application command: `streamlit run src/streamlit_app.py`.
- Streamlit Community Cloud deployment is documented in `README.md`, but there is no cloud manifest, infrastructure-as-code, hosted database configuration, or deployment settings file.

## 3. DATA FLOW

1. `DataSynthesizer.download_ibm_data()` downloads the IBM HR Analytics source dataset through KaggleHub.
2. `DataSynthesizer.generate_base_employee_data()` scales and transforms the source into the employee snapshot in `src/ETL/synthesizer.py`.
3. `generate_scd_type_2_history()` creates current and historical employee versions.
4. `generate_performance_reviews()` creates one synthetic review per employee.
5. `generate_projects()` creates 500 synthetic projects.
6. `generate_project_assignments()` creates assignments for active projects.
7. `export_to_csv()` writes five CSV files under `src/data/`.
8. `src/run_etl.py` constructs `DataWarehouseLoader` and accepts employee, history, review, project, and assignment paths.
9. `CSVExtractor.extract()` reads and parses the CSV files.
10. `DataTransformer.build_employee_history()` validates and enriches SCD2 records.
11. `_load_departments()` loads `departments` and `dim_department`.
12. `_load_oltp_projects()` loads `projects`.
13. `_load_oltp_employees()` loads `employees`.
14. `_load_oltp_assignments()` loads `project_assignments`.
15. `_load_oltp_reviews()` loads `performance_reviews`.
16. `_load_employee_versions()` loads `dim_employee` SCD2 rows.
17. `load_review_facts()` calls `sp_etl_dim_date()`.
18. `load_review_facts()` calls `sp_etl_dim_project()`.
19. `load_review_facts()` calls `sp_etl_fact_reviews()`.
20. `sp_etl_fact_reviews()` uses the `ranked_assignments` CTE and `ROW_NUMBER()` to select the latest eligible assignment and resolves the effective employee version by review date.
21. Streamlit calls `AnalyticsManager` for warehouse analytics.
22. `get_performance_trends()` reads yearly aggregates from `fact_performance_reviews`.
23. `get_top_performers()` joins facts to `dim_employee` and `dim_department` using effective-date attribution.
24. `get_attrition_risk()` aggregates current `dim_employee` records by department.
25. `get_project_bottlenecks()` aggregates active projects, assigned employees, and total allocation percentages.
26. When all analytics queries return empty, `local_analytics()` supplies local synthetic analytics.

## 4. NODES AND EDGES FOR THE DIAGRAM

### a) Nodes

| id            | label                            | layer                       | type     | technology                              |
| ------------- | -------------------------------- | --------------------------- | -------- | --------------------------------------- |
| SRC_EMP       | Synthetic employee snapshot      | Sources                     | source   | CSV                                     |
| SRC_SCD       | Employee SCD2 history            | Sources                     | source   | CSV                                     |
| SRC_REV       | Synthetic performance reviews    | Sources                     | source   | CSV                                     |
| SRC_PROJ      | Synthetic projects               | Sources                     | source   | CSV                                     |
| SRC_ASSIGN    | Synthetic project assignments    | Sources                     | source   | CSV                                     |
| SRC_ENV       | `.env` / `st.secrets` / env vars | Cross-cutting               | config   | python-dotenv, Streamlit                |
| GEN           | DataSynthesizer                  | Sources                     | process  | Python, KaggleHub, Faker, NumPy, pandas |
| EXTRACT       | CSVExtractor                     | Ingest                      | process  | Python, pandas                          |
| VALIDATE      | DataTransformer                  | Ingest                      | process  | Python, pandas                          |
| LOADER        | DataWarehouseLoader              | Ingest                      | process  | Python, PyMySQL                         |
| BRONZE        | File-based pre-load layer        | Staging (Bronze)            | source   | CSV                                     |
| DB            | `employee_analytics`             | OLTP (Silver) / OLAP (Gold) | database | MySQL                                   |
| OLTP_DEPT     | `departments`                    | OLTP (Silver)               | database | MySQL                                   |
| OLTP_EMP      | `employees`                      | OLTP (Silver)               | database | MySQL                                   |
| OLTP_PROJ     | `projects`                       | OLTP (Silver)               | database | MySQL                                   |
| OLTP_ASSIGN   | `project_assignments`            | OLTP (Silver)               | database | MySQL                                   |
| OLTP_REV      | `performance_reviews`            | OLTP (Silver)               | database | MySQL                                   |
| ETL_DATE      | `sp_etl_dim_date`                | ETL                         | process  | MySQL stored procedure                  |
| ETL_PROJ      | `sp_etl_dim_project`             | ETL                         | process  | MySQL stored procedure                  |
| ETL_FACT      | `sp_etl_fact_reviews`            | ETL                         | process  | MySQL procedure, CTE, `ROW_NUMBER()`    |
| ETL_SCD       | SCD2 employee load/update        | ETL                         | process  | Python, SQL                             |
| PROC_SCD      | `sp_close_employee_scd2_version` | ETL                         | process  | MySQL stored procedure                  |
| DIM_DEPT      | `dim_department`                 | OLAP (Gold)                 | database | MySQL                                   |
| DIM_EMP       | `dim_employee`                   | OLAP (Gold)                 | database | MySQL                                   |
| DIM_PROJ      | `dim_project`                    | OLAP (Gold)                 | database | MySQL                                   |
| DIM_DATE      | `dim_date`                       | OLAP (Gold)                 | database | MySQL                                   |
| FACT_REV      | `fact_performance_reviews`       | OLAP (Gold)                 | database | MySQL                                   |
| DB_CONN       | `DatabaseConnection`             | Application/Serve           | service  | Python, PyMySQL                         |
| MAN_EMP       | `EmployeeManager`                | Application/Serve           | service  | Python                                  |
| MAN_PROJ      | `ProjectManager`                 | Application/Serve           | service  | Python                                  |
| MAN_REV       | `ReviewManager`                  | Application/Serve           | service  | Python                                  |
| MAN_ANALYTICS | `AnalyticsManager`               | Application/Serve           | service  | Python, SQL                             |
| UI            | Streamlit application            | Application/Serve           | ui       | Streamlit, Plotly                       |
| UI_LOCAL      | Local analytics fallback         | Application/Serve           | service  | pandas                                  |
| CONSUMER_USER | End user                         | Consumers                   | ui       | Browser                                 |
| GIT           | Git branches and commits         | Cross-cutting               | devops   | Git                                     |
| CONFIG        | Streamlit theme configuration    | Cross-cutting               | config   | TOML                                    |
| CLOUD         | Streamlit Community Cloud        | Cross-cutting               | service  | Documented only                         |

`BRONZE` is a logical file-based node; no physical Bronze database or table is implemented.

### b) Edges

```text
GEN -> SRC_EMP : writes employee CSV
GEN -> SRC_SCD : writes SCD2 history CSV
GEN -> SRC_REV : writes review CSV
GEN -> SRC_PROJ : writes project CSV
GEN -> SRC_ASSIGN : writes assignment CSV
SRC_EMP -> EXTRACT : read CSV
SRC_SCD -> EXTRACT : read CSV
SRC_REV -> EXTRACT : read CSV
SRC_PROJ -> EXTRACT : read CSV
SRC_ASSIGN -> EXTRACT : read CSV
EXTRACT -> VALIDATE : parsed DataFrames
VALIDATE -> LOADER : validated employee versions
LOADER -> OLTP_DEPT : load departments
LOADER -> OLTP_EMP : batch insert employees
LOADER -> OLTP_REV : batch insert reviews
LOADER -> DIM_DEPT : load department dimension
LOADER -> OLTP_PROJ : load projects
LOADER -> OLTP_ASSIGN : load assignments
LOADER -> ETL_DATE : CALL date procedure
LOADER -> ETL_PROJ : CALL project procedure
LOADER -> ETL_FACT : CALL fact procedure
LOADER -> ETL_SCD : populate employee versions
ETL_SCD -> DIM_EMP : insert/update SCD2 versions
ETL_DATE -> DIM_DATE : insert date records
ETL_PROJ -> DIM_PROJ : insert project records
ETL_FACT -> FACT_REV : insert/update review facts
ETL_FACT -> DIM_EMP : effective-date lookup
ETL_FACT -> DIM_PROJ : project lookup
ETL_FACT -> DIM_DATE : date-key lookup
PROC_SCD -> DIM_EMP : close current version
ETL_SCD -> PROC_SCD : procedure exists but is not invoked by loader
DB_CONN -> OLTP_DEPT : connection/query
MAN_EMP -> DB_CONN : employee operations
MAN_EMP -> OLTP_EMP : create/update employees
MAN_EMP -> DIM_EMP : SCD2 updates
MAN_PROJ -> OLTP_PROJ : create projects
MAN_PROJ -> OLTP_ASSIGN : assign employees
MAN_REV -> OLTP_REV : create reviews
MAN_ANALYTICS -> FACT_REV : query trends
MAN_ANALYTICS -> DIM_EMP : query employee versions
MAN_ANALYTICS -> DIM_DEPT : query departments
MAN_ANALYTICS -> OLTP_PROJ : query active projects
MAN_ANALYTICS -> OLTP_ASSIGN : query allocations
UI -> MAN_EMP : onboarding and department lookup
UI -> MAN_PROJ : project and assignment forms
UI -> MAN_REV : review form
UI -> MAN_ANALYTICS : analytics queries
UI -> UI_LOCAL : fallback when analytics unavailable
UI_LOCAL -> SRC_EMP : read local snapshot
UI_LOCAL -> SRC_SCD : read local history
UI_LOCAL -> SRC_REV : read local reviews
SRC_ENV -> DB_CONN : database credentials
CONFIG -> UI : Streamlit theme configuration
GIT -> UI : source versioning
GIT -> GEN : source versioning
GIT -> LOADER : source versioning
GIT -> DB : schema source versioning
CLOUD -> UI : documented deployment target
CONSUMER_USER -> UI : browser access
```

## 5. GAPS AND DISCREPANCIES

- **100,000+ synthetic rows with Faker and SCD2 history: IMPLEMENTED.** Default generator downloads IBM HR data through KaggleHub, scales to 120,000 employees, creates projects and assignments, and generates 30% historical employee versions.
- **Staging, OLTP, and OLAP schemas in MySQL: PARTIAL.** OLTP and OLAP tables exist in the same `employee_analytics` database; no separate staging/Bronze MySQL schema or tables exist.
- **Star schema and surrogate keys: IMPLEMENTED.** Required fact and dimension tables, surrogate keys, and foreign keys exist in `src/database/schema.sql`.
- **Stored procedures: IMPLEMENTED for warehouse ETL; PARTIAL for runtime SCD2 close.** `sp_etl_dim_date`, `sp_etl_dim_project`, and `sp_etl_fact_reviews` are called by `DataWarehouseLoader.load_review_facts()`. `sp_close_employee_scd2_version` exists, but the Python runtime SCD2 path performs employee version updates directly rather than calling it.
- **Views: NOT IMPLEMENTED.** No SQL views are defined.
- **CTEs and window functions: IMPLEMENTED.** `ranked_assignments` uses `ROW_NUMBER()` and `get_top_performers()` uses CTEs and `DENSE_RANK()`.
- **OOP backend: IMPLEMENTED.** Entity dataclasses, database connection class, managers, validation, transactions, rollbacks, and exception handling exist.
- **Singleton `DatabaseConnection`: PARTIAL.** The singleton registry is keyed by subclass, so each manager subclass has its own singleton instance rather than all managers sharing one instance.
- **Streamlit forms: IMPLEMENTED.** Employee onboarding, project creation, employee assignment, and performance review forms exist.
- **Department change triggering SCD2: IMPLEMENTED.** Employee Management exposes department and salary updates, and `EmployeeManager.update_department()`/`_apply_scd2_change()` preserve historical versions.
- **Analytics dashboard: IMPLEMENTED for current features.** It includes year-over-year trend, top performers, attrition risk, and project bottleneck/resource allocation analytics. The former department-attribution toggle is no longer exposed; the current UI uses review-time attribution with a department filter.
- **Project allocation reporting: IMPLEMENTED.** Assignments are generated/loaded and `get_project_bottlenecks()` powers the dashboard’s resource allocation view.
- **GitHub feature branches and PRs: PARTIAL.** Branches and remotes exist, and a commit references `#1`; repository PR metadata and workflow configuration are absent.
- **GitHub Actions CI: NOT IMPLEMENTED.** No `.github` directory or workflow files exist.
- **Streamlit Cloud deployment: PARTIAL.** README documentation exists, but no deployment manifest, infrastructure code, hosted database configuration, or cloud settings file exists.
- **`st.secrets` support: IMPLEMENTED.** `src/config/settings.py` reads Streamlit secrets first and falls back to `.env`/environment variables.
- **Separate OLTP and OLAP schemas: NOT IMPLEMENTED.** Both groups are created in one MySQL schema.

## 6. ASSUMPTIONS OR UNCERTAINTIES

- No live MySQL instance or connection configuration is included, so database availability and deployed row counts cannot be verified from code inspection.
- README Streamlit Cloud deployment text is documentation, not evidence of an actual deployment.
- Git hosting PR details cannot be confirmed locally; only branches and commit messages are visible.
- SQLAlchemy, openpyxl, and related declared dependencies are not shown participating in the active application data flow.
- The stored procedure is defined in the schema, but its deployment and execution status in a live database cannot be confirmed.
- Local analytics fallback depends on the CSV files being present and matching the current code expectations.
- There is no separate Bronze database layer; the Bronze swimlane should represent file-based pre-load storage.
