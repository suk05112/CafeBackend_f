CREATE TABLE IF NOT EXISTS migration_history (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    version         VARCHAR(10),
    filename        VARCHAR(255),
    applied_at      DATETIME,
    rolled_back_at  DATETIME,
    status          ENUM('applied', 'rolled_back')
);
