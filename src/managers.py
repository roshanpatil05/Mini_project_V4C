from __future__ import annotations

from datetime import date
from typing import Any

from src.database.db_manager import DatabaseConnection
from src.models import Employee, Project, Review


class EmployeeManager(DatabaseConnection):
    def list_departments(self) -> list[dict[str, Any]]:
        return self.fetch_all("SELECT department_id, department_name FROM departments ORDER BY department_name")

    def create_employee(self, employee: Employee) -> int:
        employee.validate()
        connection = self.get_connection()
        cursor = self.execute(
            """INSERT INTO employees
               (first_name, last_name, email, department_id, job_title, hire_date, manager_id, salary, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                employee.first_name, employee.last_name, employee.email, employee.department_id,
                employee.job_title, employee.hire_date or date.today(), employee.manager_id,
                employee.salary, employee.status,
            ),
        )
        try:
            employee.employee_id = int(cursor.lastrowid)
            department = self.fetch_one(
                "SELECT department_key FROM dim_department WHERE department_id = %s",
                (employee.department_id,),
            )
            if department is None:
                raise ValueError(f"Department {employee.department_id} does not exist in the warehouse.")
            cursor.execute(
                """INSERT INTO dim_employee
                   (employee_id, first_name, last_name, email, department_key, job_title,
                    hire_date, salary, start_date, end_date, is_current, attrition_risk)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, TRUE, 0)""",
                (
                    employee.employee_id, employee.first_name, employee.last_name, employee.email,
                    department["department_key"], employee.job_title, employee.hire_date or date.today(),
                    employee.salary, date.today(),
                ),
            )
            connection.commit()
            return employee.employee_id
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()

    def update_department(self, employee_id: int, new_department_id: int) -> None:
        self._apply_scd2_change(employee_id, department_id=new_department_id)

    def update_salary(self, employee_id: int, new_salary: float) -> None:
        if new_salary <= 0:
            raise ValueError("Salary must be greater than zero.")
        self._apply_scd2_change(employee_id, salary=new_salary)

    def _apply_scd2_change(
        self,
        employee_id: int,
        department_id: int | None = None,
        salary: float | None = None,
    ) -> None:
        connection = self.get_connection()
        cursor = connection.cursor()
        today = date.today()
        try:
            cursor.execute(
                "SELECT * FROM employees WHERE employee_id = %s FOR UPDATE",
                (employee_id,),
            )
            employee = cursor.fetchone()
            if employee is None:
                raise ValueError(f"Employee {employee_id} does not exist.")
            next_department_id = department_id or employee["department_id"]
            next_salary = salary if salary is not None else employee["salary"]
            cursor.execute(
                "SELECT department_key FROM dim_department WHERE department_id = %s",
                (next_department_id,),
            )
            department = cursor.fetchone()
            if department is None:
                raise ValueError(f"Department {next_department_id} does not exist.")
            cursor.execute(
                "SELECT * FROM dim_employee WHERE employee_id = %s AND is_current = TRUE FOR UPDATE",
                (employee_id,),
            )
            current = cursor.fetchone()
            if current is None:
                raise ValueError(f"Current warehouse version for employee {employee_id} is missing.")
            if current["start_date"] == today:
                raise ValueError("An employee can have only one SCD2 change per day.")
            if (
                current["department_key"] == department["department_key"]
                and float(current["salary"]) == float(next_salary)
            ):
                connection.rollback()
                return
            cursor.execute(
                "UPDATE dim_employee SET end_date = %s, is_current = FALSE WHERE employee_key = %s",
                (today, current["employee_key"]),
            )
            cursor.execute(
                "UPDATE employees SET department_id = %s, salary = %s WHERE employee_id = %s",
                (next_department_id, next_salary, employee_id),
            )
            cursor.execute(
                """INSERT INTO dim_employee
                   (employee_id, first_name, last_name, email, department_key, job_title,
                    hire_date, salary, start_date, end_date, is_current, attrition_risk)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, TRUE, 0)""",
                (
                    employee_id, employee["first_name"], employee["last_name"], employee["email"],
                    department["department_key"], current["job_title"], employee["hire_date"],
                    next_salary, today,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()

    def list_employees(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.fetch_all(
            "SELECT employee_id, first_name, last_name, email, department_id, job_title, salary, status "
            "FROM employees WHERE status = 'active' ORDER BY employee_id DESC LIMIT %s",
            (limit,),
        )

    def get_employee(self, employee_id: int) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM employees WHERE employee_id = %s",
            (employee_id,)
        )

    def delete_employee(self, employee_id: int) -> None:
        """Deactivate an employee while preserving reviews, assignments, and SCD2 history."""
        connection = self.get_connection()
        cursor = connection.cursor()
        today = date.today()

        try:
            # Lock and verify the OLTP employee row before changing anything.
            cursor.execute(
                "SELECT employee_id, status FROM employees WHERE employee_id = %s FOR UPDATE",
                (employee_id,),
            )
            employee = cursor.fetchone()

            if employee is None:
                raise ValueError(f"Employee {employee_id} does not exist.")

            if employee["status"] == "inactive":
                raise ValueError(f"Employee {employee_id} is already inactive.")

            # Lock the current warehouse version, if one exists.
            cursor.execute(
                """SELECT employee_key
                   FROM dim_employee
                   WHERE employee_id = %s AND is_current = TRUE
                   FOR UPDATE""",
                (employee_id,),
            )
            current = cursor.fetchone()

            # Deactivate the OLTP record.
            cursor.execute(
                "UPDATE employees SET status = 'inactive' WHERE employee_id = %s",
                (employee_id,),
            )

            # Close the current SCD Type 2 version. Do not delete prior versions.
            if current:
                cursor.execute(
                    """UPDATE dim_employee
                       SET end_date = %s, is_current = FALSE
                       WHERE employee_key = %s""",
                    (today, current["employee_key"]),
                )

            # Keep existing performance reviews and project assignments for history.
            connection.commit()

        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()


class ProjectManager(DatabaseConnection):
    def create_project(self, project: Project) -> int:
        project.validate()
        cursor = self.execute(
            """INSERT INTO projects
               (project_name, department_id, budget, start_date, end_date, status)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                project.project_name, project.department_id, project.budget,
                project.start_date, project.end_date, project.status,
            ),
            commit=True,
        )
        try:
            project.project_id = int(cursor.lastrowid)
            return project.project_id
        finally:
            cursor.close()

    def assign_employee(
        self,
        employee_id: int,
        project_id: int,
        allocation_pct: float = 100,
    ) -> None:
        if not 0 < allocation_pct <= 100:
            raise ValueError("Allocation must be greater than 0 and at most 100 percent.")

        employee = self.fetch_one(
            "SELECT employee_id, status FROM employees WHERE employee_id = %s",
            (employee_id,),
        )
        if employee is None:
            raise ValueError(f"Employee {employee_id} does not exist.")
        if employee["status"] != "active":
            raise ValueError(
                f"Employee {employee_id} is inactive and cannot be assigned to a new project."
            )

        project = self.fetch_one(
            "SELECT project_id, status FROM projects WHERE project_id = %s",
            (project_id,),
        )
        if project is None:
            raise ValueError(f"Project {project_id} does not exist.")
        if project["status"] != "active":
            raise ValueError(
                f"Project {project_id} is not active and cannot receive new assignments."
            )

        cursor = self.execute(
            """INSERT INTO project_assignments
               (employee_id, project_id, allocation_pct, assigned_date)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   allocation_pct = VALUES(allocation_pct),
                   assigned_date = VALUES(assigned_date)""",
            (employee_id, project_id, allocation_pct, date.today()),
            commit=True,
        )
        cursor.close()

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        return self.fetch_one("SELECT * FROM projects WHERE project_id = %s", (project_id,))

    def list_projects(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.fetch_all("SELECT * FROM projects ORDER BY project_id DESC LIMIT %s", (limit,))

    def update_project(self, project_id: int, project_name: str, budget: float, status: str) -> None:
        cursor = self.execute(
            "UPDATE projects SET project_name = %s, budget = %s, status = %s WHERE project_id = %s",
            (project_name, budget, status, project_id),
            commit=True,
        )
        cursor.close()

    def delete_project(self, project_id: int) -> None:
        cursor = self.execute("DELETE FROM projects WHERE project_id = %s", (project_id,), commit=True)
        cursor.close()


class ReviewManager(DatabaseConnection):
    def create_review(self, review: Review) -> int:
        review.validate()
        cursor = self.execute(
            """INSERT INTO performance_reviews
               (employee_id, review_date, manager_id, overall_score, rating, comments)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                review.employee_id, review.review_date, review.manager_id,
                review.overall_score, review.rating, review.comments,
            ),
            commit=True,
        )
        try:
            return int(cursor.lastrowid)
        finally:
            cursor.close()

    def get_review(self, review_id: int) -> dict[str, Any] | None:
        return self.fetch_one("SELECT * FROM performance_reviews WHERE review_id = %s", (review_id,))

    def list_reviews(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.fetch_all("SELECT * FROM performance_reviews ORDER BY review_date DESC LIMIT %s", (limit,))

    def delete_review(self, review_id: int) -> None:
        cursor = self.execute("DELETE FROM performance_reviews WHERE review_id = %s", (review_id,), commit=True)
        cursor.close()

    def update_review(self, review_id: int, overall_score: float, rating: str, comments: str) -> None:
        cursor = self.execute(
            "UPDATE performance_reviews SET overall_score = %s, rating = %s, comments = %s WHERE review_id = %s",
            (overall_score, rating, comments, review_id),
            commit=True,
        )
        cursor.close()


class AnalyticsManager(DatabaseConnection):
    def get_performance_trends(self, department_basis: str = "review", department_name: str | None = None) -> list[dict[str, Any]]:
        employee_join = {
            "review": """JOIN dim_employee e
                ON e.employee_id = f.employee_id
                AND f.review_date >= e.start_date
                AND (e.end_date IS NULL OR f.review_date < e.end_date)""",
            "current": """JOIN dim_employee e
                ON e.employee_id = f.employee_id AND e.is_current = TRUE""",
        }
        if department_basis not in employee_join:
            raise ValueError("department_basis must be 'review' or 'current'")
            
        where_clause = ""
        params = []
        if department_name and department_name != "All departments":
            where_clause = "WHERE d.department_name = %s"
            params.append(department_name)
            
        query = f"""
            SELECT YEAR(f.review_date) AS review_year, AVG(f.overall_score) AS avg_score
            FROM fact_performance_reviews f
            {employee_join[department_basis]}
            JOIN dim_department d ON d.department_key = e.department_key
            {where_clause}
            GROUP BY YEAR(f.review_date)
            ORDER BY review_year
        """
        return self.fetch_all(query, tuple(params) if params else None)

    def get_top_performers(self, department_basis: str = "review", department_name: str | None = None) -> list[dict[str, Any]]:
        employee_join = {
            "review": """JOIN dim_employee e
                ON e.employee_id = f.employee_id
                AND f.review_date >= e.start_date
                AND (e.end_date IS NULL OR f.review_date < e.end_date)""",
            "current": """JOIN dim_employee e
                ON e.employee_id = f.employee_id AND e.is_current = TRUE""",
        }
        if department_basis not in employee_join:
            raise ValueError("department_basis must be 'review' or 'current'")
            
        where_clause = ""
        params = []
        if department_name and department_name != "All departments":
            where_clause = "WHERE d.department_name = %s"
            params.append(department_name)
            
        query = f"""
            WITH employee_scores AS (
                SELECT f.employee_id, e.first_name, e.last_name,
                       d.department_name, AVG(f.overall_score) AS overall_score
                FROM fact_performance_reviews f
                {employee_join[department_basis]}
                JOIN dim_department d ON d.department_key = e.department_key
                {where_clause}
                GROUP BY f.employee_id, e.first_name, e.last_name, d.department_name
            ), ranked AS (
                SELECT employee_id, first_name, last_name, department_name, overall_score,
                       DENSE_RANK() OVER (
                           PARTITION BY department_name ORDER BY overall_score DESC
                       ) AS department_rank
                FROM employee_scores
            )
            SELECT * FROM ranked
            WHERE department_rank <= 5
            ORDER BY department_name, department_rank, employee_id
        """
        return self.fetch_all(query, tuple(params) if params else None)

    def get_attrition_risk(self, department_name: str | None = None) -> list[dict[str, Any]]:
        where_clause = "WHERE e.is_current = TRUE"
        params = []
        if department_name and department_name != "All departments":
            where_clause += " AND d.department_name = %s"
            params.append(department_name)
            
        query = f"""SELECT d.department_name, COUNT(*) AS employees,
                      AVG(e.performance_score) AS avg_performance,
                      AVG(e.attrition_risk) AS avg_attrition_risk
               FROM dim_employee e
               JOIN dim_department d ON d.department_key = e.department_key
               {where_clause}
               GROUP BY d.department_name ORDER BY avg_attrition_risk DESC"""
        return self.fetch_all(query, tuple(params) if params else None)

    def get_project_bottlenecks(self, department_name: str | None = None) -> list[dict[str, Any]]:
        where_clause = "WHERE p.status = 'active'"
        params = []
        if department_name and department_name != "All departments":
            where_clause += " AND d.department_name = %s"
            params.append(department_name)
            
        query = f"""SELECT p.project_id, p.project_name, d.department_name, p.budget,
                      COUNT(e.employee_id) AS assigned_employees,
                      COALESCE(SUM(CASE WHEN e.employee_id IS NOT NULL THEN a.allocation_pct ELSE 0 END), 0) AS total_allocation_pct
               FROM projects p
               JOIN departments d ON p.department_id = d.department_id
               LEFT JOIN project_assignments a ON p.project_id = a.project_id
               LEFT JOIN employees e ON a.employee_id = e.employee_id AND e.status = 'active'
               {where_clause}
               GROUP BY p.project_id, p.project_name, d.department_name, p.budget
               ORDER BY total_allocation_pct ASC, assigned_employees ASC
               LIMIT 10"""
        return self.fetch_all(query, tuple(params) if params else None)

    def get_overview_metrics(self) -> dict[str, Any]:
        total_employees = self.fetch_one("SELECT COUNT(*) as count FROM employees WHERE status = 'active'")["count"]
        total_departments = self.fetch_one("SELECT COUNT(*) as count FROM departments")["count"]
        avg_score_row = self.fetch_one("SELECT AVG(overall_score) as avg_score FROM performance_reviews")
        avg_score = float(avg_score_row["avg_score"]) if avg_score_row["avg_score"] is not None else 0.0
        
        distribution = self.fetch_all("""
            SELECT d.department_name, COUNT(e.employee_id) as size
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
            WHERE e.status = 'active'
            GROUP BY d.department_name
            ORDER BY size ASC
        """)
        
        return {
            "total_employees": total_employees,
            "total_departments": total_departments,
            "average_score": avg_score,
            "distribution": distribution
        }
    #commenta
