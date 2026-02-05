-- 기존 약관 테이블 제거 후 새 스키마로 생성 (유저/사장님 구분, terms_version 공지·시행·재동의)
-- 주의: user_terms_agreement, owner_terms_agreement 데이터가 있으면 삭제됩니다.

DROP TABLE IF EXISTS user_terms_agreement;
DROP TABLE IF EXISTS owner_terms_agreement;
DROP TABLE IF EXISTS terms_version;
DROP TABLE IF EXISTS terms;

-- 약관 종류 테이블 (target: user=유저용, owner=사장님용)
CREATE TABLE terms (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    target VARCHAR(10) NOT NULL COMMENT 'user=유저용, owner=사장님용',
    term_type VARCHAR(50) NOT NULL COMMENT 'SERVICE, PRIVACY, LOCATION, MARKETING 등',
    title VARCHAR(255) NOT NULL COMMENT '표시명',
    required BOOLEAN NOT NULL DEFAULT TRUE COMMENT '가입 시 필수 동의 여부',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    UNIQUE KEY uk_terms_target_term_type (target, term_type),
    INDEX idx_terms_target (target),
    INDEX idx_terms_term_type (term_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='약관 종류 테이블';

-- 약관 버전 테이블 (공지일, 시행일, 버전별 재동의 여부)
CREATE TABLE terms_version (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    term_id INT NOT NULL COMMENT 'FK terms.id',
    version VARCHAR(20) NOT NULL COMMENT '1.0, 1.1, 2.0 등',
    notice_date DATE NOT NULL COMMENT '공지일',
    effective_date DATE NOT NULL COMMENT '시행일 (공지 후 30일 이후)',
    reagreement_required BOOLEAN NOT NULL COMMENT 'TRUE=재동의 필수, FALSE=공지만(시행 후 자동 동의 저장)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    UNIQUE KEY uk_terms_version_term_version (term_id, version),
    INDEX idx_terms_version_term_id (term_id),
    INDEX idx_terms_version_effective (effective_date),
    CONSTRAINT fk_terms_version_term FOREIGN KEY (term_id) REFERENCES terms(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='약관 버전 테이블';

-- 유저별 약관 동의 기록
CREATE TABLE user_terms_agreement (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    user_id INT NOT NULL COMMENT 'user.id',
    term_version_id INT NOT NULL COMMENT 'terms_version.id',
    agreed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '동의 시각',
    UNIQUE KEY uk_user_terms_agreement_user_version (user_id, term_version_id),
    INDEX idx_user_terms_agreement_user (user_id),
    INDEX idx_user_terms_agreement_agreed (user_id, agreed_at),
    INDEX idx_user_terms_agreement_version (term_version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='유저 약관 동의 기록';

-- 사장님별 약관 동의 기록
CREATE TABLE owner_terms_agreement (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    owner_id BIGINT(20) NOT NULL COMMENT 'owner.id',
    term_version_id INT NOT NULL COMMENT 'terms_version.id',
    agreed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '동의 시각',
    UNIQUE KEY uk_owner_terms_agreement_owner_version (owner_id, term_version_id),
    INDEX idx_owner_terms_agreement_owner (owner_id),
    INDEX idx_owner_terms_agreement_agreed (owner_id, agreed_at),
    INDEX idx_owner_terms_agreement_version (term_version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='사장님 약관 동의 기록';
