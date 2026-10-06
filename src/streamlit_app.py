from __future__ import annotations

import sys
from pathlib import Path

# Add the project root to sys.path so 'src.*' imports work on Streamlit Cloud
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pandas as pd
import plotly.express as px
import streamlit as st

from src.managers import AnalyticsManager, EmployeeManager, ProjectManager, ReviewManager
from src.models import Employee, Project, Review
from src.ui.theme import (
    COLORS,
    COLOURWAY,
    apply_theme,
    info_pill,
    kpi_card,
    page_header,
    score_band,
    section_title,
    status_badge,
    style_fig,
)


apply_theme()

DATA_DIR = Path(__file__).resolve().parent / "data"
PAGES = ["Overview", "Employee Onboarding", "Project Management", "Performance Reviews", "Analytics Dashboard"]
PAGE_ICONS = {"Overview": " ", "Employee Onboarding": " ", "Project Management": " ", "Performance Reviews": " ", "Analytics Dashboard": " "}
# PAGE_ICONS = {"Overview": "◈", "Employee Onboarding": "＋", "Project Management": "◆", "Performance Reviews": "✓", "Analytics Dashboard": "◒"}

# @st.cache_data
def load_local_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    employees_path = DATA_DIR / "synthetic_employees.csv"
    history_path = DATA_DIR / "employee_scd2_history.csv"
    reviews_path = DATA_DIR / "synthetic_performance_reviews.csv"
    if not all(path.exists() for path in (employees_path, history_path, reviews_path)):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    employees = pd.read_csv(employees_path, parse_dates=["hire_date"])
    history = pd.read_csv(history_path, parse_dates=["start_date", "end_date"])
    reviews = pd.read_csv(reviews_path, parse_dates=["review_date"])
    return employees, history, reviews


def local_analytics(department_basis: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    employees, history, reviews = load_local_data()
    if employees.empty:
        trend = pd.DataFrame({"review_year": [2023, 2024, 2025], "avg_score": [82.4, 85.1, 87.6]})
        top = pd.DataFrame(
            {
                "employee_id": [101, 203, 156, 287],
                "first_name": ["Alicia", "Daniel", "Priya", "Morgan"],
                "last_name": ["Stone", "Nguyen", "Rao", "West"],
                "department_name": ["Engineering", "Sales", "Finance", "Operations"],
                "overall_score": [96, 94, 92, 91],
                "department_rank": [1, 1, 1, 1],
            }
        )
        risk = pd.DataFrame(
            {
                "department_name": ["Engineering", "Sales", "Finance", "Operations"],
                "employees": [1200, 980, 720, 640],
                "avg_performance": [88, 80, 86, 82],
                "avg_attrition_risk": [24, 38, 29, 34],
            }
        )
        return trend, top, risk

    if department_basis == "review":
        department_versions = history[["employee_id", "department_name", "start_date", "end_date"]]
        review_rows = reviews.merge(department_versions, on="employee_id", how="inner")
        review_rows = review_rows[
            (review_rows["review_date"] >= review_rows["start_date"])
            & (review_rows["end_date"].isna() | (review_rows["review_date"] < review_rows["end_date"]))
        ]
    else:
        current = history.loc[history["is_current"].astype(bool), ["employee_id", "department_name"]]
        review_rows = reviews.merge(current, on="employee_id", how="inner")

    identity = employees[["employee_id", "first_name", "last_name"]]
    review_rows = review_rows.merge(identity, on="employee_id", how="left", validate="many_to_one")
    trend = (
        review_rows.assign(review_year=review_rows["review_date"].dt.year)
        .groupby("review_year", as_index=False)["overall_score"]
        .mean()
        .rename(columns={"overall_score": "avg_score"})
    )
    top = (
        review_rows.groupby(["employee_id", "first_name", "last_name", "department_name"], as_index=False)["overall_score"]
        .mean()
    )
    top["department_rank"] = top.groupby("department_name")["overall_score"].rank(method="dense", ascending=False)
    top = top[top["department_rank"] <= 5].sort_values(["department_name", "department_rank"])

    current_history = history[history["is_current"].astype(bool)]
    risk = (
        current_history.groupby("department_name", as_index=False)
        .agg(
            employees=("employee_id", "count"),
            avg_performance=("performance_score", "mean"),
            avg_attrition_risk=("attrition_risk", "mean"),
        )
        .sort_values("avg_attrition_risk", ascending=False)
    )
    return trend, top, risk


def get_department_choices() -> list[dict]:
    try:
        return EmployeeManager().list_departments()
    except Exception:
        return []


def render_form_message(message: str, success: bool) -> None:
    if success:
        st.success(message)
    else:
        st.error(message)

def render_department_field(departments: list[dict], key: str = "department") -> int:
    if departments:
        choices = {row["department_name"]: row["department_id"] for row in departments}
        selected = st.selectbox("Department", list(choices), key=key)
        return int(choices[selected])
    st.caption("Use the department ID when the warehouse is unavailable.")
    return int(st.number_input("Department ID", min_value=1, step=1, key=f"{key}_id"))


def render_overview() -> None:
    page_header("Enterprise Employee <span class='gradient-text'>Analytics</span>", "People, performance, and project allocation")
    section_title("Workforce overview")
    
    warehouse_connected = bool(get_department_choices())
    
    # Try fetching from MySQL first
    if warehouse_connected:
        try:
            metrics = AnalyticsManager().get_overview_metrics()
            total_employees = metrics["total_employees"]
            departments = metrics["total_departments"]
            average_score = f"{metrics['average_score']:.1f}"
            counts = pd.DataFrame(metrics["distribution"])
        except Exception:
            warehouse_connected = False

    # Fallback to CSV if MySQL is unreachable or failed
    if not warehouse_connected:
        employees, _, reviews = load_local_data()
        departments = int(employees["department_name"].nunique()) if not employees.empty else 8
        average_score = f"{reviews['overall_score'].mean():.1f}" if not reviews.empty else "--"
        total_employees = len(employees) if not employees.empty else 100_000
        counts = employees.groupby("department_name", as_index=False).size().sort_values("size", ascending=True) if not employees.empty else pd.DataFrame()
        info_pill("Showing local synthetic data for the overview page (MySQL connection failed)")

    kpis = st.columns(4)
    with kpis[0]:
        kpi_card("Total employees", f"{total_employees:,}", icon="♙")
    with kpis[1]:
        kpi_card("Departments", departments, icon="⌘")
    with kpis[2]:
        kpi_card("Data source", "MySQL" if warehouse_connected else "Local preview", icon="◉")
    with kpis[3]:
        kpi_card("Average review score", average_score, icon="✦")
        
    st.markdown("<div style='height:.9rem'></div>", unsafe_allow_html=True)
    status_badge("Connected to MySQL" if warehouse_connected else "Local preview", "success" if warehouse_connected else "warning")
    
    if not counts.empty:
        fig = px.bar(
            counts,
            x="size",
            y="department_name",
            orientation="h",
            text="size",
            color="size",
            color_continuous_scale=[[0, COLORS["bg_purple"]], [.55, COLORS["magenta"]], [1, COLORS["pink"]]],
            labels={"size": "Employees", "department_name": "Department"},
            title="Employees by department",
        )
        fig.update_traces(texttemplate="%{text:,}", textposition="outside", hovertemplate="%{y}: %{x:,}<extra></extra>")
        fig.update_layout(coloraxis_showscale=False, xaxis_title="Employees", yaxis_title="Department")
        with st.container(border=True):
            section_title("Workforce distribution")
            st.plotly_chart(style_fig(fig, 410), use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("Generate the included sample data with `python -m src.ETL.synthesizer` to preview workforce metrics.")


def render_onboarding() -> None:
    page_header("Employee <span class='gradient-text'>onboarding</span>", "Create a workforce record and place it in the warehouse")
    departments = get_department_choices()
    with st.container(border=True):
        section_title("New employee profile")
        with st.form("employee_form"):
            first_col, last_col = st.columns(2)
            with first_col:
                first_name = st.text_input("First name")
                email = st.text_input("Work email")
            with last_col:
                last_name = st.text_input("Last name")
                job_title = st.text_input("Job title")
            department_col, salary_col = st.columns(2)
            with department_col:
                department_id = render_department_field(departments, "employee_department")
            with salary_col:
                salary = st.number_input("Annual salary", min_value=1_000.0, step=1_000.0, format="%.2f")
            st.caption("Employee details are validated before they are written to OLTP and the current warehouse dimension.")
            submitted = st.form_submit_button("Add employee", type="primary", use_container_width=True)
    if submitted:
        employee = Employee(first_name=first_name, last_name=last_name, email=email, department_id=department_id, job_title=job_title, salary=float(salary))
        try:
            employee_id = EmployeeManager().create_employee(employee)
            render_form_message(f"Employee {employee_id} added. The current employee record was created.", True)
        except Exception as exc:
            render_form_message(f"Employee could not be added: {exc}", False)


def render_projects() -> None:
    page_header("Project <span class='gradient-text'>management</span>", "Create initiatives and balance employee allocations")
    departments = get_department_choices()
    create_tab, assign_tab = st.tabs(["Create project", "Assign employee"])
    with create_tab:
        with st.container(border=True):
            section_title("Project brief")
            with st.form("project_form"):
                project_name = st.text_input("Project name")
                department_col, budget_col = st.columns(2)
                with department_col:
                    department_id = render_department_field(departments, "project_department")
                with budget_col:
                    budget = st.number_input("Budget", min_value=0.0, step=5_000.0, format="%.2f")
                create_project = st.form_submit_button("Create project", type="primary", use_container_width=True)
        if create_project:
            try:
                project_id = ProjectManager().create_project(Project(project_name=project_name, department_id=department_id, budget=float(budget)))
                render_form_message(f"Project {project_id} created.", True)
            except Exception as exc:
                render_form_message(f"Project could not be created: {exc}", False)
    with assign_tab:
        with st.container(border=True):
            section_title("Allocation details")
            with st.form("assignment_form"):
                employee_col, project_col = st.columns(2)
                with employee_col:
                    employee_id = st.number_input("Employee ID", min_value=1, step=1)
                with project_col:
                    project_id = st.number_input("Project ID", min_value=1, step=1)
                allocation = st.slider("Allocation", min_value=5, max_value=100, value=100, step=5, format="%d%%")
                st.caption("Allocation is capped at 100% by the existing project manager validation.")
                assign = st.form_submit_button("Assign employee", type="primary", use_container_width=True)
        if assign:
            try:
                ProjectManager().assign_employee(int(employee_id), int(project_id), float(allocation))
                render_form_message("Project allocation saved.", True)
            except Exception as exc:
                render_form_message(f"Allocation could not be saved: {exc}", False)


def render_reviews() -> None:
    page_header("Performance <span class='gradient-text'>reviews</span>", "Capture a clear, consistent view of employee performance")
    with st.container(border=True):
        section_title("Review details")
        with st.form("review_form"):
            identity_col, date_col = st.columns(2)
            with identity_col:
                employee_id = st.number_input("Employee ID", min_value=1, step=1)
            with date_col:
                review_date = st.date_input("Review date")
            score = st.slider("Overall score", min_value=0.0, max_value=100.0, value=80.0, step=0.5)
            band, band_color = score_band(score)
            st.markdown(f'<span class="score-band" style="color:{band_color}; border-color:{band_color}55">●&nbsp; {band} · {score:.1f}/100</span>', unsafe_allow_html=True)
            rating = st.selectbox("Rating", ["Exceeds Expectations", "Strong", "Meets Expectations", "Needs Improvement"])
            comments = st.text_area("Manager comments", height=130)
            submit_review = st.form_submit_button("Save review", type="primary", use_container_width=True)
    if submit_review:
        try:
            review_id = ReviewManager().create_review(Review(employee_id=int(employee_id), review_date=review_date, overall_score=float(score), rating=rating, comments=comments))
            render_form_message(f"Review {review_id} saved. Run the warehouse ETL to refresh analytics.", True)
        except Exception as exc:
            render_form_message(f"Review could not be saved: {exc}", False)


def render_analytics() -> None:
    page_header("Performance <span class='gradient-text'>analytics</span>", "Read workforce momentum, high performers, and risk at a glance")
    department_label = st.radio(
        "Attribute reviews to",
        ["Department at time of review", "Current department"],
        horizontal=True,
        help="Historical attribution uses the employee dimension version effective on the review date.",
    )
    department_basis = "review" if department_label == "Department at time of review" else "current"
    analytics = AnalyticsManager()
    try:
        trend = pd.DataFrame(analytics.get_performance_trends())
    except Exception:
        trend = pd.DataFrame()
    try:
        top = pd.DataFrame(analytics.get_top_performers(department_basis))
    except Exception:
        top = pd.DataFrame()
    try:
        risk = pd.DataFrame(analytics.get_attrition_risk())
    except Exception:
        risk = pd.DataFrame()
    local_fallback = trend.empty or top.empty or risk.empty
    if local_fallback:
        local_trend, local_top, local_risk = local_analytics(department_basis)
        trend = trend if not trend.empty else local_trend
        top = top if not top.empty else local_top
        risk = risk if not risk.empty else local_risk
        info_pill("Showing local synthetic analytics for any view not available from MySQL")

    latest_score = float(trend.iloc[-1]["avg_score"]) if not trend.empty else 0
    year_change = float(trend.iloc[-1]["avg_score"] - trend.iloc[-2]["avg_score"]) if len(trend) > 1 else 0
    reviewed_count = int(top["employee_id"].nunique()) if not top.empty else 0
    high_risk_count = int((risk["avg_attrition_risk"] >= 60).sum()) if not risk.empty else 0
    kpis = st.columns(4)
    with kpis[0]:
        kpi_card("Latest average score", f"{latest_score:.1f}", icon="✦")
    with kpis[1]:
        kpi_card("Year-over-year change", f"{year_change:+.1f}", "score points", icon="↗")
    with kpis[2]:
        kpi_card("Employees reviewed", f"{reviewed_count:,}", icon="♙")
    with kpis[3]:
        kpi_card("High-risk departments", high_risk_count, "average risk ≥ 60", icon="◌")

    chart_columns = st.columns(2)
    if not trend.empty:
        with chart_columns[0].container(border=True):
            section_title("Year-over-year review score")
            fig = px.line(trend, x="review_year", y="avg_score", markers=True, labels={"review_year": "Year", "avg_score": "Average review score"})
            fig.update_traces(line={"color": COLORS["pink"], "width": 3}, marker={"color": COLORS["soft_pink"], "size": 9}, fill="tozeroy", fillcolor="rgba(185,58,150,.16)", hovertemplate="Year %{x}<br>Average review score %{y:.1f}<extra></extra>")
            padding = max(1, (float(trend["avg_score"].max()) - float(trend["avg_score"].min())) * 0.35)
            fig.update_layout(xaxis={"dtick": 1, "tickformat": "d", "title": "Year"}, yaxis={"range": [trend["avg_score"].min() - padding, trend["avg_score"].max() + padding], "title": "Average review score"})
            st.plotly_chart(style_fig(fig, 365), use_container_width=True, config={"displayModeBar": False})
            st.caption(f"Review scores moved {year_change:+.1f} points in the latest year.")
    if not top.empty:
        top = top.copy()
        departments = ["All departments"] + sorted(top["department_name"].dropna().unique().tolist())
        selected_department = chart_columns[1].selectbox("Filter top performers", departments)
        filtered_top = top if selected_department == "All departments" else top[top["department_name"] == selected_department]
        filtered_top = filtered_top.sort_values("overall_score", ascending=True).tail(10)
        filtered_top["employee_name"] = filtered_top["first_name"] + " " + filtered_top["last_name"]
        with chart_columns[1].container(border=True):
            section_title("Top performers")
            fig = px.bar(filtered_top, x="overall_score", y="employee_name", orientation="h", color="department_name", text="overall_score", color_discrete_sequence=COLOURWAY, labels={"overall_score": "Average score", "employee_name": "Employee", "department_name": "Department"})
            fig.update_traces(texttemplate="%{text:.1f}", textposition="outside", hovertemplate="%{y}<br>Average score %{x:.1f}<extra></extra>")
            fig.update_layout(showlegend=False, xaxis_title="Average score", yaxis_title="Employee")
            st.plotly_chart(style_fig(fig, 365), use_container_width=True, config={"displayModeBar": False})
            st.caption("The strongest average performers across the selected department view.")

    if not risk.empty:
        with st.container(border=True):
            section_title("Attrition risk by department")
            risk_display = risk.sort_values("avg_attrition_risk", ascending=True)
            fig = px.bar(risk_display, x="avg_attrition_risk", y="department_name", orientation="h", text="avg_attrition_risk", color="avg_attrition_risk", color_continuous_scale=[[0, COLORS["soft_pink"]], [.5, COLORS["magenta"]], [1, COLORS["bg_indigo"]]], labels={"avg_attrition_risk": "Average attrition risk", "department_name": "Department"})
            fig.update_traces(texttemplate="%{text:.1f}", textposition="outside", hovertemplate="%{y}<br>Average attrition risk %{x:.1f}<extra></extra>")
            fig.update_layout(coloraxis_showscale=False, xaxis_title="Average attrition risk", yaxis_title="Department")
            st.plotly_chart(style_fig(fig, 390), use_container_width=True, config={"displayModeBar": False})
            st.caption("Higher values indicate departments that may benefit from a closer retention review.")

    if not top.empty:
        display_top = top[["employee_id", "first_name", "last_name", "department_name", "overall_score", "department_rank"]].copy()
        display_top.columns = ["Employee ID", "First name", "Last name", "Department", "Average score", "Department rank"]
        with st.container(border=True):
            section_title("Performance roster")
            st.dataframe(display_top.sort_values("Average score", ascending=False), hide_index=True, use_container_width=True)


st.sidebar.markdown('<div class="brand-mark"><span>V4C</span>.ai</div>', unsafe_allow_html=True)
page = st.sidebar.radio("Workspace", [f"{PAGE_ICONS[item]}  {item}" for item in PAGES], label_visibility="collapsed")
page = page.split("  ", 1)[1].strip()

if page == "Overview":
    render_overview()
elif page == "Employee Onboarding":
    render_onboarding()
elif page == "Project Management":
    render_projects()
elif page == "Performance Reviews":
    render_reviews()
else:
    render_analytics()

#commend
