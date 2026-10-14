CREATE TABLE IF NOT EXISTS client_features (
    client_id INT NOT NULL,
    feature_key VARCHAR(64) NOT NULL,
    is_enabled BOOLEAN NOT NULL,
    updated_by INT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (client_id, feature_key),
    CONSTRAINT fk_feature_client FOREIGN KEY (client_id) REFERENCES clients(id),
    CONSTRAINT fk_feature_actor FOREIGN KEY (updated_by) REFERENCES users(id),
    CONSTRAINT chk_feature_enabled CHECK (is_enabled IN (0,1))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS feature_audit_logs (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    feature_key VARCHAR(64) NOT NULL,
    old_enabled BOOLEAN NOT NULL,
    new_enabled BOOLEAN NOT NULL,
    changed_by INT NOT NULL,
    changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_feature_audit_client (client_id, id),
    CONSTRAINT fk_feature_audit_client FOREIGN KEY (client_id) REFERENCES clients(id),
    CONSTRAINT fk_feature_audit_actor FOREIGN KEY (changed_by) REFERENCES users(id),
    CONSTRAINT chk_feature_audit_old CHECK (old_enabled IN (0,1)),
    CONSTRAINT chk_feature_audit_new CHECK (new_enabled IN (0,1))
) ENGINE=InnoDB;

INSERT IGNORE INTO client_features (client_id, feature_key, is_enabled)
SELECT id, 'payroll', 0 FROM clients;

INSERT IGNORE INTO client_features (client_id, feature_key, is_enabled)
SELECT id, 'attendance_corrections', 1 FROM clients;

INSERT IGNORE INTO client_features (client_id, feature_key, is_enabled)
SELECT id, 'gajiku', 0 FROM clients;
