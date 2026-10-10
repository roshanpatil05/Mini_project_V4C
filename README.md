# Enterprise Employee Analytics & Data Warehouse

An object-oriented employee analytics project with a normalized MySQL OLTP schema, a dimensional warehouse, SCD Type 2 employee history, a Streamlit application, and a reproducible 100,000-employee synthetic dataset.

## Project layout

```text
src/
	config/                 Environment-backed MySQL settings
	database/               Connection manager, schema, editable diagrams
	ETL/                     Extract, transform, synthesize, and load classes
	data/                    Generated CSV artifacts (created by the generator)
	managers.py              Employee, project, review, and analytics managers
	models.py                Validated OOP entities
	run_etl.py               CSV-to-MySQL ETL command
	run_schema.py            Executes schema.sql to setup tables and stored procedures
	streamlit_app.py         Web application and analytics dashboard
tests/                     Focused SCD2 and dashboard-query tests
```

The OLTP ER diagram and star-schema diagram are editable Mermaid files in `src/database/`.

## Setup

Use Python 3.10 or newer and MySQL 8.0 or newer. Install dependencies from the repository root:

```bash
python -m pip install -r requirements.txt
```

Set database credentials in a root `.env` file or the shell environment. The supported variables are `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME` (defaults to `localhost:3306`, user `root`, and database `employee_analytics`).

## Generate the dataset

```bash
python -m src.ETL.synthesizer --rows 100000 --historical-fraction 0.30
```

The command writes three CSVs to `src/data/`:

- `synthetic_employees.csv`: 100,000 employee snapshot rows.
- `employee_scd2_history.csv`: one current version per employee plus a prior effective-dated version for 30% of employees.
- `synthetic_performance_reviews.csv`: one dated review per employee.

Generation is reproducible with `--seed`; use `--output-dir` to write elsewhere. Historical versions have non-overlapping effective dates, and generated review dates fall after hire dates.

## Create and load the database

Run `src/database/schema.sql` in MySQL Workbench, or simply use the provided Python script:

```bash
python run_schema.py
```

Then load the generated CSVs into OLTP and the warehouse:

```bash
python -m src.run_etl
```

The ETL script calls custom **Stored Procedures** (`sp_etl_dim_date`, `sp_etl_dim_project`, `sp_etl_fact_reviews`) residing in your MySQL schema to perform the heavy transformation. These procedures batch large CSVs, map department business IDs to warehouse surrogate keys, create date/project dimensions, rank assignments with a window function (`ROW_NUMBER()`), and resolve each fact to the `dim_employee` version effective on its review date. Employee department/salary changes close the prior dimension row and insert a current row in one transaction.

## Run the application

```bash
streamlit run src/streamlit_app.py
```

The app provides a comprehensive UI including:
- **Full CRUD Management**: Search, Update, and Soft Delete capabilities across Employees, Projects, and Performance Reviews. Updating an employee's department or salary automatically triggers an SCD Type 2 tracking update in the backend warehouse.
- **Analytics Dashboard**: Interactive Plotly charts analyzing year-over-year performance trends, top-performing employees by department, attrition risk, and **Project Bottlenecks** (active projects suffering from resource shortages).

If the warehouse is unavailable, analytics use the local generated CSVs so the dashboards and department toggle remain demonstrable; database write forms still require a configured MySQL server.

### Department attribution toggle

The analytics page offers **Department at time of review** and **Current department**:

- **At time of review** joins each review to the employee dimension version where `start_date <= review_date < end_date` (or the version has no end date). This preserves historical department attribution after transfers.
- **Current department** joins to the employee's `is_current = TRUE` version, restating all of that employee's reviews under today's department.

Both views use the same review scores and department-level dense ranking; only the department attribution changes.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests cover generated SCD2 intervals, review dates, both department-attribution SQL paths, and rejection of unrecognized dashboard modes. A live MySQL server is needed to integration-test database writes and ETL execution.

## Cloud deployment

Deploy the repository with Streamlit Community Cloud and set the `DB_*` values in the app's secrets. The MySQL host must accept connections from the deployment environment. For a no-database demo, generate the CSV artifacts before deployment and deploy the dashboard with the synthetic data included.
