CREATE DATABASE IF NOT EXISTS elrise_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE elrise_db;

CREATE TABLE IF NOT EXISTS clients (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    code VARCHAR(32) NOT NULL UNIQUE,
    email VARCHAR(190) NOT NULL,
    phone VARCHAR(32) NOT NULL DEFAULT '',
    address VARCHAR(500) NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT 0,
    employee_limit INT NOT NULL DEFAULT 50,
    service_start DATE NOT NULL,
    service_end DATE NOT NULL,
    photo_retention_days INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_client_limit CHECK (employee_limit BETWEEN 1 AND 100000),
    CONSTRAINT chk_client_period CHECK (service_end >= service_start),
    CONSTRAINT chk_client_retention CHECK (photo_retention_days IS NULL OR photo_retention_days BETWEEN 1 AND 365)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS users (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id INT NULL,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(190) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('superadmin','admin','employee') NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    session_version INT NOT NULL DEFAULT 1,
    must_change_password BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_tenant (id, client_id),
    INDEX idx_user_client_role (client_id, role),
    CONSTRAINT fk_user_client FOREIGN KEY (client_id) REFERENCES clients(id),
    CONSTRAINT chk_user_role_tenant CHECK ((role = 'superadmin' AND client_id IS NULL) OR (role <> 'superadmin' AND client_id IS NOT NULL))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS office_locations (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    name VARCHAR(120) NOT NULL,
    address VARCHAR(500) NOT NULL DEFAULT '',
    latitude DECIMAL(10,7) NOT NULL,
    longitude DECIMAL(10,7) NOT NULL,
    radius_m INT NOT NULL DEFAULT 100,
    max_accuracy_m INT NOT NULL DEFAULT 50,
    start_time TIME NOT NULL DEFAULT '09:00:00',
    end_time TIME NOT NULL DEFAULT '17:00:00',
    working_days VARCHAR(13) NOT NULL DEFAULT '1,2,3,4,5',
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_office_tenant (id, client_id),
    CONSTRAINT fk_office_client FOREIGN KEY (client_id) REFERENCES clients(id),
    CONSTRAINT chk_office_lat CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT chk_office_lon CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT chk_office_radius CHECK (radius_m BETWEEN 10 AND 5000),
    CONSTRAINT chk_office_accuracy CHECK (max_accuracy_m BETWEEN 1 AND 200),
    CONSTRAINT chk_office_shift CHECK (end_time > start_time)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS employees (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    user_id INT NOT NULL UNIQUE,
    office_id INT NULL,
    employee_number VARCHAR(32) NOT NULL,
    name VARCHAR(120) NOT NULL,
    department VARCHAR(120) NOT NULL DEFAULT '',
    job_title VARCHAR(120) NOT NULL DEFAULT '',
    phone VARCHAR(32) NOT NULL DEFAULT '',
    join_date DATE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    privacy_accepted_at DATETIME NULL,
    privacy_version VARCHAR(32) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_employee_tenant (id, client_id),
    UNIQUE KEY uq_employee_number (client_id, employee_number),
    INDEX idx_employee_office (office_id, client_id),
    CONSTRAINT fk_employee_client FOREIGN KEY (client_id) REFERENCES clients(id),
    CONSTRAINT fk_employee_user FOREIGN KEY (user_id, client_id) REFERENCES users(id, client_id),
    CONSTRAINT fk_employee_office FOREIGN KEY (office_id, client_id) REFERENCES office_locations(id, client_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS attendances (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    employee_id INT NOT NULL,
    office_id INT NOT NULL,
    work_date DATE NOT NULL,
    status ENUM('present','late') NOT NULL,
    late_minutes INT NOT NULL DEFAULT 0,
    office_name VARCHAR(120) NOT NULL,
    office_latitude DECIMAL(10,7) NOT NULL,
    office_longitude DECIMAL(10,7) NOT NULL,
    office_radius_m INT NOT NULL,
    office_max_accuracy_m INT NOT NULL,
    scheduled_start TIME NOT NULL,
    scheduled_end TIME NOT NULL,
    check_in_at DATETIME NOT NULL,
    check_in_latitude DECIMAL(10,7) NOT NULL,
    check_in_longitude DECIMAL(10,7) NOT NULL,
    check_in_accuracy DECIMAL(9,2) NOT NULL,
    check_in_distance DECIMAL(10,2) NOT NULL,
    check_in_device_at DATETIME NOT NULL,
    check_in_photo VARCHAR(255) NULL,
    check_out_at DATETIME NULL,
    check_out_latitude DECIMAL(10,7) NULL,
    check_out_longitude DECIMAL(10,7) NULL,
    check_out_accuracy DECIMAL(9,2) NULL,
    check_out_distance DECIMAL(10,2) NULL,
    check_out_device_at DATETIME NULL,
    check_out_photo VARCHAR(255) NULL,
    UNIQUE KEY uq_attendance_day (client_id, employee_id, work_date),
    INDEX idx_attendance_date (client_id, work_date, status),
    INDEX idx_attendance_office (office_id, client_id),
    CONSTRAINT fk_attendance_client FOREIGN KEY (client_id) REFERENCES clients(id),
    CONSTRAINT fk_attendance_employee FOREIGN KEY (employee_id, client_id) REFERENCES employees(id, client_id),
    CONSTRAINT fk_attendance_office FOREIGN KEY (office_id, client_id) REFERENCES office_locations(id, client_id),
    CONSTRAINT chk_attendance_order CHECK (check_out_at IS NULL OR check_out_at >= check_in_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS leave_requests (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    employee_id INT NOT NULL,
    kind ENUM('izin','cuti','sakit') NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    status ENUM('pending','approved','rejected','canceled') NOT NULL DEFAULT 'pending',
    admin_note VARCHAR(500) NOT NULL DEFAULT '',
    reviewed_by INT NULL,
    reviewed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_leave_tenant_status (client_id, status, start_date, end_date),
    INDEX idx_leave_employee (employee_id, client_id),
    INDEX idx_leave_reviewer (reviewed_by, client_id),
    CONSTRAINT fk_leave_client FOREIGN KEY (client_id) REFERENCES clients(id),
    CONSTRAINT fk_leave_employee FOREIGN KEY (employee_id, client_id) REFERENCES employees(id, client_id),
    CONSTRAINT fk_leave_reviewer FOREIGN KEY (reviewed_by, client_id) REFERENCES users(id, client_id),
    CONSTRAINT chk_leave_period CHECK (end_date >= start_date)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS login_limits (
    bucket CHAR(64) NOT NULL PRIMARY KEY,
    attempts INT NOT NULL DEFAULT 0,
    window_started_at DATETIME NOT NULL,
    INDEX idx_limit_expiry (window_started_at)
) ENGINE=InnoDB;
