from __future__ import annotations

import argparse
from pathlib import Path
import os

import numpy as np
import pandas as pd
from faker import Faker
import kagglehub

class DataSynthesizer:
	"""Create reproducible employee snapshots, projects, assignments and SCD Type 2 versions by scaling IBM HR dataset."""

	def __init__(
		self,
		rows: int = 120_000,
		historical_fraction: float = 0.30,
		seed: int = 42,
	) -> None:
		if rows < 1:
			raise ValueError("rows must be greater than zero")
		if not 0 <= historical_fraction <= 1:
			raise ValueError("historical_fraction must be between 0 and 1")
		self.rows = rows
		self.historical_fraction = historical_fraction
		self.seed = seed
		self.rng = np.random.default_rng(self.seed)

	def download_ibm_data(self) -> pd.DataFrame:
		print("Downloading IBM HR Analytics Dataset...")
		path = kagglehub.dataset_download("pavansubhasht/ibm-hr-analytics-attrition-dataset")
		csv_files = list(Path(path).glob("*.csv"))
		if not csv_files:
			raise FileNotFoundError("No CSV found in the downloaded dataset")
		return pd.read_csv(csv_files[0])

	def generate_base_employee_data(self) -> pd.DataFrame:
		ibm_df = self.download_ibm_data()
		print(f"Scaling base dataset from {len(ibm_df)} to {self.rows} rows...")
		
		sampled_df = ibm_df.sample(n=self.rows, replace=True, random_state=self.seed).reset_index(drop=True)
		
		today = pd.Timestamp.today().normalize()
		fake = Faker()
		fake.seed_instance(self.seed)
		
		years_at_company = sampled_df["YearsAtCompany"].to_numpy()
		jitter_days = self.rng.integers(0, 365, self.rows)
		hire_dates = today - pd.to_timedelta((years_at_company * 365) + jitter_days, unit="D")
		
		attrition = sampled_df["Attrition"].astype(str).str.lower()
		is_attrition = (attrition == "yes").to_numpy()
		attrition_risk = np.zeros(self.rows, dtype=int)
		attrition_risk[is_attrition] = self.rng.integers(70, 100, size=np.sum(is_attrition))
		attrition_risk[~is_attrition] = self.rng.integers(0, 50, size=np.sum(~is_attrition))
		
		perf_rating = sampled_df["PerformanceRating"].to_numpy()
		performance_score = (perf_rating - 1) * 25 + self.rng.integers(0, 25, self.rows)
		
		# Initialize departments and roles using the native IBM data
		assigned_depts = sampled_df["Department"].to_numpy()
		job_titles = sampled_df["JobRole"].to_numpy()
		
		# Reassign 50% of the employees to the new departments to give them distinct distributions
		change_mask = self.rng.random(self.rows) < 0.50
		new_departments = ["Engineering", "Operations", "Finance"]
		dept_probs = [0.60, 0.20, 0.20] # 60% Eng, 20% Ops, 20% Fin
		
		assigned_depts[change_mask] = self.rng.choice(new_departments, size=np.sum(change_mask), p=dept_probs)
		
		NEW_ROLES = {
			"Engineering": ["Software Engineer", "Data Engineer", "Engineering Manager"],
			"Operations": ["Operations Analyst", "Operations Manager", "Project Coordinator"],
			"Finance": ["Financial Analyst", "Finance Manager", "Controller"]
		}
		for dept, roles in NEW_ROLES.items():
			mask = (assigned_depts == dept) & change_mask
			job_titles[mask] = self.rng.choice(roles, size=np.sum(mask))

		# Apply distributions (modifiers) to the new departments
		is_eng = assigned_depts == "Engineering"
		is_ops = assigned_depts == "Operations"
		is_fin = assigned_depts == "Finance"

		performance_score[is_eng] += 15
		attrition_risk[is_eng] -= 20
		
		performance_score[is_ops] -= 10
		attrition_risk[is_ops] += 10

		attrition_risk[is_fin] -= 15
		
		
		performance_score = np.clip(performance_score, 0, 100)
		attrition_risk = np.clip(attrition_risk, 0, 100)
		
		first_names = [fake.first_name() for _ in range(self.rows)]
		last_names = [fake.last_name() for _ in range(self.rows)]
		emails = [f"employee{i}@example.com" for i in range(1, self.rows + 1)]
		
		employees = pd.DataFrame(
			{
				"employee_id": np.arange(1, self.rows + 1, dtype=np.int64),
				"first_name": first_names,
				"last_name": last_names,
				"email": emails,
				"department_name": assigned_depts,
				"job_title": job_titles,
				"hire_date": hire_dates,
				"salary": sampled_df["MonthlyIncome"].to_numpy() * 12.0,
				"performance_score": performance_score,
				"attrition_risk": attrition_risk,
			}
		)
		employees["manager_id"] = self.rng.integers(1, max(2, self.rows // 50), self.rows)
		return employees

	def generate_projects(self, employees: pd.DataFrame) -> pd.DataFrame:
		fake = Faker()
		fake.seed_instance(self.seed + 3)
		num_projects = 500
		
		unique_departments = employees["department_name"].unique()
		departments = self.rng.choice(unique_departments, size=num_projects)
		budgets = self.rng.integers(10000, 5000000, size=num_projects)
		
		return pd.DataFrame({
			"project_id": np.arange(1, num_projects + 1, dtype=np.int64),
			"project_name": [fake.bs().title() + " Initiative" for _ in range(num_projects)],
			"department_name": departments,
			"budget": budgets,
			"status": self.rng.choice(["active", "planned", "completed", "on_hold"], size=num_projects, p=[0.6, 0.2, 0.15, 0.05])
		})

	def generate_project_assignments(self, employees: pd.DataFrame, projects: pd.DataFrame) -> pd.DataFrame:
		active_projects = projects[projects["status"] == "active"]["project_id"].to_numpy()
		
		assignment_counts = self.rng.choice([0, 1, 2, 3], size=len(employees), p=[0.4, 0.4, 0.15, 0.05])
		total_assignments = assignment_counts.sum()
		
		assigned_emp_ids = np.repeat(employees["employee_id"].to_numpy(), assignment_counts)
		assigned_proj_ids = self.rng.choice(active_projects, size=total_assignments)
		
		assignment_records = pd.DataFrame({
			"assignment_id": np.arange(1, total_assignments + 1, dtype=np.int64),
			"project_id": assigned_proj_ids,
			"employee_id": assigned_emp_ids,
			"role": self.rng.choice(["Lead", "Contributor", "Reviewer"], size=total_assignments),
			"allocation_pct": self.rng.choice([10, 25, 50, 75, 100], size=total_assignments),
			"assigned_date": pd.Timestamp.today().normalize() - pd.to_timedelta(self.rng.integers(10, 100, size=total_assignments), unit="D")
		})
		
		assignment_records = assignment_records.drop_duplicates(subset=["employee_id", "project_id"]).reset_index(drop=True)
		assignment_records["assignment_id"] = np.arange(1, len(assignment_records) + 1, dtype=np.int64)
		
		return assignment_records

	def generate_scd_type_2_history(self, employees: pd.DataFrame) -> pd.DataFrame:
		today = pd.Timestamp.today().normalize()
		historical_count = int(len(employees) * self.historical_fraction)
		changed_ids = set(
			self.rng.choice(employees["employee_id"].to_numpy(), size=historical_count, replace=False).tolist()
		)
		history = employees[
			[
				"employee_id", "department_name", "job_title", "salary", "hire_date",
				"performance_score", "attrition_risk",
			]
		].copy()
		history["start_date"] = history["hire_date"]
		history["end_date"] = pd.NaT
		history["is_current"] = True

		if changed_ids:
			changed = history[history["employee_id"].isin(changed_ids)].copy()
			earliest_changes = np.maximum(
				changed["hire_date"].to_numpy(dtype="datetime64[ns]")
				+ np.timedelta64(30, "D"),
				(today - pd.Timedelta(days=730)).to_datetime64(),
			)
			latest_change = (today - pd.Timedelta(days=30)).to_datetime64()
			available_days = (latest_change - earliest_changes).astype("timedelta64[D]").astype(int)
			
			# Avoid negative high ranges
			available_days = np.maximum(available_days, 1)
			
			change_dates = pd.to_datetime(
				earliest_changes
				+ self.rng.integers(0, available_days + 1, len(changed)).astype("timedelta64[D]")
			)
			changed["end_date"] = change_dates
			changed["is_current"] = False
			changed["salary"] = (changed["salary"] * self.rng.uniform(0.84, 0.96, len(changed))).round(2)
			
			unique_departments = list(employees["department_name"].unique())
			if len(unique_departments) > 1:
				changed["department_name"] = [
					self.rng.choice([d for d in unique_departments if d != current])
					for current in changed["department_name"]
				]
				
			# Assign a sensible job title for the new department
			NEW_ROLES = {
				"Engineering": ["Software Engineer", "Data Engineer", "Engineering Manager"],
				"Operations": ["Operations Analyst", "Operations Manager", "Project Coordinator"],
				"Finance": ["Financial Analyst", "Finance Manager", "Controller"]
			}
			ibm_roles = ["Sales Executive", "Research Scientist", "Laboratory Technician", "Manufacturing Director", "Healthcare Representative", "Manager", "Sales Representative", "Research Director", "Human Resources"]
			
			def get_random_role(dept):
				if dept in NEW_ROLES: return self.rng.choice(NEW_ROLES[dept])
				return self.rng.choice(ibm_roles)
				
			changed["job_title"] = [get_random_role(d) for d in changed["department_name"]]

			current_mask = history["employee_id"].isin(changed_ids)
			history.loc[current_mask, "start_date"] = change_dates.to_numpy()
			history = pd.concat([history, changed], ignore_index=True)

		history = history.drop(columns="hire_date")
		return history.sort_values(["employee_id", "start_date"]).reset_index(drop=True)

	def generate_performance_reviews(self, employees: pd.DataFrame) -> pd.DataFrame:
		today = pd.Timestamp.today().normalize()
		earliest_dates = np.maximum(
			employees["hire_date"].to_numpy(dtype="datetime64[ns]"),
			(today - pd.DateOffset(years=3)).to_datetime64(),
		)
		available_days = (today.to_datetime64() - earliest_dates).astype("timedelta64[D]").astype(int)
		available_days = np.maximum(available_days, 1)
		
		review_dates = pd.to_datetime(
			earliest_dates + self.rng.integers(0, available_days + 1).astype("timedelta64[D]")
		)
		
		scores = employees["performance_score"].to_numpy()
		
		ratings = np.select(
			[scores >= 90, scores >= 80, scores >= 70],
			["Exceeds Expectations", "Strong", "Meets Expectations"],
			default="Needs Improvement",
		)
		return pd.DataFrame(
			{
				"review_id": np.arange(1, len(employees) + 1, dtype=np.int64),
				"employee_id": employees["employee_id"].to_numpy(),
				"review_date": review_dates,
				"overall_score": scores,
				"rating": ratings,
				"comments": "Synthetic annual performance review",
			}
		)

	def export_to_csv(self, output_dir: str | Path | None = None) -> dict[str, Path]:
		destination = Path(output_dir) if output_dir else Path(__file__).resolve().parents[1] / "data"
		destination.mkdir(parents=True, exist_ok=True)
		
		employees = self.generate_base_employee_data()
		history = self.generate_scd_type_2_history(employees)
		reviews = self.generate_performance_reviews(employees)
		projects = self.generate_projects(employees)
		assignments = self.generate_project_assignments(employees, projects)
		
		employee_path = destination / "synthetic_employees.csv"
		history_path = destination / "employee_scd2_history.csv"
		review_path = destination / "synthetic_performance_reviews.csv"
		project_path = destination / "synthetic_projects.csv"
		assignment_path = destination / "synthetic_project_assignments.csv"
		
		print("Writing CSVs...")
		employees.to_csv(employee_path, index=False, date_format="%Y-%m-%d")
		history.to_csv(history_path, index=False, date_format="%Y-%m-%d")
		reviews.to_csv(review_path, index=False, date_format="%Y-%m-%d")
		projects.to_csv(project_path, index=False)
		assignments.to_csv(assignment_path, index=False, date_format="%Y-%m-%d")
		
		return {
			"employees": employee_path, 
			"history": history_path, 
			"reviews": review_path,
			"projects": project_path,
			"assignments": assignment_path
		}


def main() -> None:
	parser = argparse.ArgumentParser(description="Generate employee snapshot and SCD2 history CSV files")
	parser.add_argument("--rows", type=int, default=120_000)
	parser.add_argument("--historical-fraction", type=float, default=0.30)
	parser.add_argument("--seed", type=int, default=42)
	parser.add_argument("--output-dir", type=Path, default=None)
	args = parser.parse_args()
	paths = DataSynthesizer(args.rows, args.historical_fraction, args.seed).export_to_csv(args.output_dir)
	for label, path in paths.items():
		print(f"{label}: {path}")


if __name__ == "__main__":
	main()
