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
            "SELECT employee_id, first_name, last_name, email, department_id, job_title, salary "
            "FROM employees ORDER BY employee_id DESC LIMIT %s",
            (limit,),
        )


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

    def assign_employee(self, employee_id: int, project_id: int, allocation_pct: float = 100) -> None:
        if not 0 < allocation_pct <= 100:
            raise ValueError("Allocation must be greater than 0 and at most 100 percent.")
        cursor = self.execute(
            """INSERT INTO project_assignments (employee_id, project_id, allocation_pct, assigned_date)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE allocation_pct = VALUES(allocation_pct), assigned_date = VALUES(assigned_date)""",
            (employee_id, project_id, allocation_pct, date.today()),
            commit=True,
        )
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


class AnalyticsManager(DatabaseConnection):
    def get_performance_trends(self) -> list[dict[str, Any]]:
        return self.fetch_all(
            """SELECT YEAR(review_date) AS review_year, AVG(overall_score) AS avg_score
               FROM fact_performance_reviews GROUP BY YEAR(review_date) ORDER BY review_year"""
        )

    def get_top_performers(self, department_basis: str = "review") -> list[dict[str, Any]]:
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
        query = f"""
            WITH employee_scores AS (
                SELECT f.employee_id, e.first_name, e.last_name,
                       d.department_name, AVG(f.overall_score) AS overall_score
                FROM fact_performance_reviews f
                {employee_join[department_basis]}
                JOIN dim_department d ON d.department_key = e.department_key
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
        return self.fetch_all(query)

    def get_attrition_risk(self) -> list[dict[str, Any]]:
        return self.fetch_all(
            """SELECT d.department_name, COUNT(*) AS employees,
                      AVG(e.performance_score) AS avg_performance,
                      AVG(e.attrition_risk) AS avg_attrition_risk
               FROM dim_employee e
               JOIN dim_department d ON d.department_key = e.department_key
               WHERE e.is_current = TRUE
               GROUP BY d.department_name ORDER BY avg_attrition_risk DESC"""
        )

    def get_overview_metrics(self) -> dict[str, Any]:
        total_employees = self.fetch_one("SELECT COUNT(*) as count FROM employees")["count"]
        total_departments = self.fetch_one("SELECT COUNT(*) as count FROM departments")["count"]
        avg_score_row = self.fetch_one("SELECT AVG(overall_score) as avg_score FROM performance_reviews")
        avg_score = float(avg_score_row["avg_score"]) if avg_score_row["avg_score"] is not None else 0.0
        
        distribution = self.fetch_all("""
            SELECT d.department_name, COUNT(e.employee_id) as size
            FROM employees e
            JOIN departments d ON e.department_id = d.department_id
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
