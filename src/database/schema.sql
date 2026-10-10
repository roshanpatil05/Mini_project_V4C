CREATE DATABASE IF NOT EXISTS employee_analytics;
USE employee_analytics;

CREATE TABLE IF NOT EXISTS departments (
    department_id INT AUTO_INCREMENT PRIMARY KEY,
    department_name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    department_id INT NOT NULL,
    job_title VARCHAR(120) NOT NULL,
    hire_date DATE NOT NULL,
    manager_id BIGINT NULL,
    salary DECIMAL(12, 2) NOT NULL,
    performance_score DECIMAL(5, 2) NOT NULL DEFAULT 0,
    attrition_risk TINYINT UNSIGNED NOT NULL DEFAULT 0,
    status ENUM('active', 'inactive') NOT NULL DEFAULT 'active',
    CONSTRAINT fk_employee_department FOREIGN KEY (department_id) REFERENCES departments(department_id),
    CONSTRAINT fk_employee_manager FOREIGN KEY (manager_id) REFERENCES employees(employee_id)
);

CREATE TABLE IF NOT EXISTS projects (
    project_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_name VARCHAR(160) NOT NULL,
    department_id INT NOT NULL,
    budget DECIMAL(14, 2) NOT NULL DEFAULT 0,
    start_date DATE NULL,
    end_date DATE NULL,
    status ENUM('planned', 'active', 'completed', 'on_hold') NOT NULL DEFAULT 'active',
    CONSTRAINT fk_project_department FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

CREATE TABLE IF NOT EXISTS project_assignments (
    assignment_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    employee_id BIGINT NOT NULL,
    project_id BIGINT NOT NULL,
    allocation_pct DECIMAL(5, 2) NOT NULL DEFAULT 100,
    assigned_date DATE NOT NULL,
    CONSTRAINT fk_assignment_employee FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
    CONSTRAINT fk_assignment_project FOREIGN KEY (project_id) REFERENCES projects(project_id),
    CONSTRAINT uq_project_assignment UNIQUE (employee_id, project_id)
);

CREATE TABLE IF NOT EXISTS performance_reviews (
    review_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    employee_id BIGINT NOT NULL,
    review_date DATE NOT NULL,
    manager_id BIGINT NULL,
    overall_score DECIMAL(5, 2) NOT NULL,
    rating VARCHAR(40) NOT NULL,
    comments TEXT NULL,
    CONSTRAINT fk_review_employee FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
    CONSTRAINT fk_review_manager FOREIGN KEY (manager_id) REFERENCES employees(employee_id),
    CONSTRAINT chk_review_score CHECK (overall_score BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS dim_department (
    department_key INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL UNIQUE,
    department_name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS dim_employee (
    employee_key BIGINT AUTO_INCREMENT PRIMARY KEY,
    employee_id BIGINT NOT NULL,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    email VARCHAR(255) NOT NULL,
    department_key INT NOT NULL,
    job_title VARCHAR(120) NOT NULL,
    hire_date DATE NOT NULL,
    salary DECIMAL(12, 2) NOT NULL,
    performance_score DECIMAL(5, 2) NOT NULL DEFAULT 0,
    attrition_risk TINYINT UNSIGNED NOT NULL DEFAULT 0,
    start_date DATE NOT NULL,
    end_date DATE NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT fk_dim_employee_department FOREIGN KEY (department_key) REFERENCES dim_department(department_key),
    CONSTRAINT uq_dim_employee_version UNIQUE (employee_id, start_date),
    INDEX ix_dim_employee_asof (employee_id, start_date, end_date, is_current)
);

CREATE TABLE IF NOT EXISTS dim_project (
    project_key BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id BIGINT NOT NULL UNIQUE,
    project_name VARCHAR(160) NOT NULL,
    department_key INT NOT NULL,
    CONSTRAINT fk_dim_project_department FOREIGN KEY (department_key) REFERENCES dim_department(department_key)
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_key INT PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,
    year_num SMALLINT NOT NULL,
    quarter_num TINYINT NOT NULL,
    month_num TINYINT NOT NULL,
    day_num TINYINT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_performance_reviews (
    fact_review_key BIGINT AUTO_INCREMENT PRIMARY KEY,
    review_id BIGINT NOT NULL UNIQUE,
    employee_key BIGINT NOT NULL,
    employee_id BIGINT NOT NULL,
    department_key INT NOT NULL,
    project_key BIGINT NULL,
    date_key INT NOT NULL,
    review_date DATE NOT NULL,
    overall_score DECIMAL(5, 2) NOT NULL,
    rating VARCHAR(40) NOT NULL,
    CONSTRAINT fk_fact_employee FOREIGN KEY (employee_key) REFERENCES dim_employee(employee_key),
    CONSTRAINT fk_fact_department FOREIGN KEY (department_key) REFERENCES dim_department(department_key),
    CONSTRAINT fk_fact_project FOREIGN KEY (project_key) REFERENCES dim_project(project_key),
    CONSTRAINT fk_fact_date FOREIGN KEY (date_key) REFERENCES dim_date(date_key),
    INDEX ix_fact_review_date (review_date),
    INDEX ix_fact_employee_id (employee_id)
);

DROP PROCEDURE IF EXISTS sp_close_employee_scd2_version;
DELIMITER $$
CREATE PROCEDURE sp_close_employee_scd2_version(
    IN p_employee_id BIGINT,
    IN p_effective_date DATE
)
BEGIN
    UPDATE dim_employee
    SET end_date = p_effective_date, is_current = FALSE
    WHERE employee_id = p_employee_id AND is_current = TRUE;
END$$
DELIMITER ;

DROP PROCEDURE IF EXISTS sp_etl_dim_date;
DELIMITER $$
CREATE PROCEDURE sp_etl_dim_date()
BEGIN
    INSERT INTO dim_date (date_key, full_date, year_num, quarter_num, month_num, day_num)
    SELECT DISTINCT YEAR(review_date) * 10000 + MONTH(review_date) * 100 + DAY(review_date),
           review_date, YEAR(review_date), QUARTER(review_date),
           MONTH(review_date), DAY(review_date)
    FROM performance_reviews
    ON DUPLICATE KEY UPDATE full_date = VALUES(full_date);
END$$
DELIMITER ;

DROP PROCEDURE IF EXISTS sp_etl_dim_project;
DELIMITER $$
CREATE PROCEDURE sp_etl_dim_project()
BEGIN
    INSERT INTO dim_project (project_id, project_name, department_key)
    SELECT p.project_id, p.project_name, d.department_key
    FROM projects p
    JOIN departments source_department ON source_department.department_id = p.department_id
    JOIN dim_department d ON d.department_id = source_department.department_id
    ON DUPLICATE KEY UPDATE project_name = VALUES(project_name),
                            department_key = VALUES(department_key);
END$$
DELIMITER ;

DROP PROCEDURE IF EXISTS sp_etl_fact_reviews;
DELIMITER $$
CREATE PROCEDURE sp_etl_fact_reviews()
BEGIN
    INSERT INTO fact_performance_reviews (
        review_id, employee_key, employee_id, department_key, project_key,
        date_key, review_date, overall_score, rating
    )
    WITH ranked_assignments AS (
        SELECT pr.review_id, pa.project_id,
               ROW_NUMBER() OVER (
                   PARTITION BY pr.review_id ORDER BY pa.assigned_date DESC, pa.assignment_id DESC
               ) AS assignment_rank
        FROM performance_reviews pr
        LEFT JOIN project_assignments pa
          ON pa.employee_id = pr.employee_id AND pa.assigned_date <= pr.review_date
    )
    SELECT pr.review_id, e.employee_key, pr.employee_id, e.department_key,
           dp.project_key,
           YEAR(pr.review_date) * 10000 + MONTH(pr.review_date) * 100 + DAY(pr.review_date),
           pr.review_date, pr.overall_score, pr.rating
    FROM performance_reviews pr
    JOIN dim_employee e
      ON e.employee_id = pr.employee_id
     AND pr.review_date >= e.start_date
     AND (e.end_date IS NULL OR pr.review_date < e.end_date)
    LEFT JOIN ranked_assignments ra
      ON ra.review_id = pr.review_id AND ra.assignment_rank = 1
    LEFT JOIN dim_project dp ON dp.project_id = ra.project_id
    ON DUPLICATE KEY UPDATE employee_key = VALUES(employee_key),
                            department_key = VALUES(department_key),
                            project_key = VALUES(project_key),
                            overall_score = VALUES(overall_score), rating = VALUES(rating);
END$$
DELIMITER ;
