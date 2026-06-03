"""
약관(terms) CRUD: 현재 시행 약관 조회, 유저 동의 상태/저장, 관리자 약관·버전 관리
"""
import pymysql
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple


def _date_serial(obj: Any) -> Any:
    """date/datetime to ISO string for JSON"""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat() if hasattr(obj, 'isoformat') else str(obj)
    return obj


def get_current_terms(conn, target: str) -> List[Dict]:
    """
    현재 시행 중인 약관 목록 (effective_date <= 오늘, term당 최신 버전 1개).
    target: 'user' | 'owner'
    회원가입/재동의 화면 노출용.
    """
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        today = date.today()
        cursor.execute("""
            SELECT t.id AS term_id, t.term_type, t.title, t.required,
                   tv.id AS term_version_id, tv.version, tv.notice_date, tv.effective_date, tv.reagreement_required
            FROM terms t
            INNER JOIN terms_version tv ON tv.term_id = t.id
            INNER JOIN (
                SELECT term_id, MAX(id) AS max_id
                FROM terms_version
                WHERE effective_date <= %s
                GROUP BY term_id
            ) latest ON latest.term_id = t.id AND latest.max_id = tv.id
            WHERE tv.effective_date <= %s AND t.target = %s
            ORDER BY t.id
        """, (today, today, target))
        rows = cursor.fetchall()
        result = []
        for r in rows:
            result.append({
                "term_id": r["term_id"],
                "term_type": r["term_type"],
                "title": r["title"],
                "required": bool(r["required"]),
                "version": r["version"],
                "term_version_id": r["term_version_id"],
                "notice_date": _date_serial(r["notice_date"]),
                "effective_date": _date_serial(r["effective_date"]),
                "reagreement_required": bool(r["reagreement_required"]),
            })
        return result
    finally:
        cursor.close()


def get_user_terms_status(conn, user_id: int) -> Dict:
    """
    유저의 약관별 동의 상태. 재동의 필요 여부(needs_reagreement) 포함.
    공지만(reagreement_required=FALSE)이고 시행일 지난 버전은 동의 기록 없으면 자동 저장 후 동의한 것으로 반환.
    """
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        today = date.today()
        # 현재 시행 중인 버전만 (term당 최신 1개, 유저용만)
        cursor.execute("""
            SELECT t.id AS term_id, t.term_type, t.title, t.required,
                   tv.id AS current_version_id, tv.version AS current_version, tv.reagreement_required
            FROM terms t
            INNER JOIN terms_version tv ON tv.term_id = t.id
            INNER JOIN (
                SELECT term_id, MAX(id) AS max_id
                FROM terms_version
                WHERE effective_date <= %s
                GROUP BY term_id
            ) latest ON latest.term_id = t.id AND latest.max_id = tv.id
            WHERE tv.effective_date <= %s AND t.target = 'user'
            ORDER BY t.id
        """, (today, today))
        current_versions = {row["term_id"]: row for row in cursor.fetchall()}

        # 해당 유저의 동의 기록 (현재 시행 버전에 해당하는 것만)
        version_ids = [v["current_version_id"] for v in current_versions.values()]
        if not version_ids:
            return {"user_id": user_id, "terms_status": [], "has_pending_reagreement": False}

        placeholders = ",".join(["%s"] * len(version_ids))
        cursor.execute(f"""
            SELECT term_version_id, agreed_at
            FROM user_terms_agreement
            WHERE user_id = %s AND term_version_id IN ({placeholders})
        """, (user_id, *version_ids))
        agreed = {r["term_version_id"]: r for r in cursor.fetchall()}

        terms_status = []
        has_pending = False
        for term_id, cur in current_versions.items():
            vid = cur["current_version_id"]
            agreed_row = agreed.get(vid)
            reagreement_required = bool(cur["reagreement_required"])

            if agreed_row:
                agreed_at = agreed_row["agreed_at"]
                agreed_version_id = vid
                agreed_version = cur["current_version"]
                needs_reagreement = False
            else:
                if reagreement_required:
                    needs_reagreement = True
                    has_pending = True
                    agreed_at = None
                    agreed_version_id = None
                    agreed_version = None
                else:
                    # 공지만: 시행일 지났으면 동의한 걸로 간주하고 저장
                    cursor.execute("""
                        INSERT IGNORE INTO user_terms_agreement (user_id, term_version_id, agreed_at)
                        VALUES (%s, %s, %s)
                    """, (user_id, vid, today))
                    conn.commit()
                    agreed_at = today
                    agreed_version_id = vid
                    agreed_version = cur["current_version"]
                    needs_reagreement = False

            terms_status.append({
                "term_id": term_id,
                "term_type": cur["term_type"],
                "title": cur["title"],
                "required": bool(cur["required"]),
                "current_version_id": vid,
                "current_version": cur["current_version"],
                "agreed_version_id": agreed_version_id,
                "agreed_version": agreed_version,
                "agreed_at": _date_serial(agreed_at),
                "needs_reagreement": needs_reagreement,
            })
        return {
            "user_id": user_id,
            "terms_status": terms_status,
            "has_pending_reagreement": has_pending,
        }
    finally:
        cursor.close()


def validate_user_agreements(conn, agreements: List[Dict]) -> Tuple[bool, Optional[str]]:
    """
    약관 동의 검증만 수행 (저장 없음). 필수 약관(required)은 agreed=True 여야 함.
    반환: (valid, error_message)
    """
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        today = date.today()
        cursor.execute("""
            SELECT t.id AS term_id, t.required, tv.id AS term_version_id
            FROM terms t
            INNER JOIN terms_version tv ON tv.term_id = t.id
            INNER JOIN (
                SELECT term_id, MAX(id) AS max_id FROM terms_version
                WHERE effective_date <= %s
                GROUP BY term_id
            ) latest ON latest.term_id = t.id AND latest.max_id = tv.id
            WHERE tv.effective_date <= %s AND t.target = 'user'
        """, (today, today))
        current_map = {r["term_id"]: r for r in cursor.fetchall()}
        req_term_ids = {tid for tid, r in current_map.items() if r["required"]}
        by_term = {a["term_id"]: a for a in agreements}
        for term_id in req_term_ids:
            if term_id not in by_term or not by_term[term_id].get("agreed"):
                cursor.execute("SELECT title FROM terms WHERE id = %s", (term_id,))
                row = cursor.fetchone()
                title = row["title"] if row else "필수 약관"
                return False, f"필수 약관({title})에 동의해 주세요."
        return True, None
    finally:
        cursor.close()


def save_user_agreements(
    conn, user_id: int, agreements: List[Dict]
) -> Tuple[bool, Optional[str], int]:
    """
    agreements: [{"term_id": int, "term_version_id": int, "agreed": bool}, ...]
    필수 약관(required)은 agreed=True 여야 함.
    반환: (success, error_message, agreed_count)
    """
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        today = date.today()
        # 현재 시행 약관 (term_id -> term_version_id, required)
        cursor.execute("""
            SELECT t.id AS term_id, t.required, tv.id AS term_version_id
            FROM terms t
            INNER JOIN terms_version tv ON tv.term_id = t.id
            INNER JOIN (
                SELECT term_id, MAX(id) AS max_id FROM terms_version
                WHERE effective_date <= %s
                GROUP BY term_id
            ) latest ON latest.term_id = t.id AND latest.max_id = tv.id
            WHERE tv.effective_date <= %s AND t.target = 'user'
        """, (today, today))
        current_map = {r["term_id"]: r for r in cursor.fetchall()}
        req_term_ids = {tid for tid, r in current_map.items() if r["required"]}

        by_term = {a["term_id"]: a for a in agreements}
        for term_id in req_term_ids:
            if term_id not in by_term or not by_term[term_id].get("agreed"):
                cursor.execute("SELECT title FROM terms WHERE id = %s", (term_id,))
                row = cursor.fetchone()
                title = row["title"] if row else "필수 약관"
                return False, f"필수 약관({title})에 동의해 주세요.", 0

        agreed_count = 0
        for a in agreements:
            term_id = a.get("term_id")
            term_version_id = a.get("term_version_id")
            agreed = a.get("agreed", False)
            if term_id not in current_map or current_map[term_id]["term_version_id"] != term_version_id:
                continue
            if not agreed:
                continue
            cursor.execute("""
                INSERT INTO user_terms_agreement (user_id, term_version_id, agreed_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE agreed_at = VALUES(agreed_at)
            """, (user_id, term_version_id, today))
            agreed_count += 1
        conn.commit()
        return True, None, agreed_count
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cursor.close()


# ---------- Owner (사장님) ----------

def get_owner_terms_status(conn, owner_id: int) -> Dict:
    """
    사장님의 약관별 동의 상태. 재동의 필요 여부 포함.
    공지만(reagreement_required=FALSE)이고 시행일 지난 버전은 동의 기록 없으면 자동 저장.
    """
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        today = date.today()
        cursor.execute("""
            SELECT t.id AS term_id, t.term_type, t.title, t.required,
                   tv.id AS current_version_id, tv.version AS current_version, tv.reagreement_required
            FROM terms t
            INNER JOIN terms_version tv ON tv.term_id = t.id
            INNER JOIN (
                SELECT term_id, MAX(id) AS max_id
                FROM terms_version
                WHERE effective_date <= %s
                GROUP BY term_id
            ) latest ON latest.term_id = t.id AND latest.max_id = tv.id
            WHERE tv.effective_date <= %s AND t.target = 'owner'
            ORDER BY t.id
        """, (today, today))
        current_versions = {row["term_id"]: row for row in cursor.fetchall()}

        version_ids = [v["current_version_id"] for v in current_versions.values()]
        if not version_ids:
            return {"owner_id": owner_id, "terms_status": [], "has_pending_reagreement": False}

        placeholders = ",".join(["%s"] * len(version_ids))
        cursor.execute(f"""
            SELECT term_version_id, agreed_at
            FROM owner_terms_agreement
            WHERE owner_id = %s AND term_version_id IN ({placeholders})
        """, (owner_id, *version_ids))
        agreed = {r["term_version_id"]: r for r in cursor.fetchall()}

        terms_status = []
        has_pending = False
        for term_id, cur in current_versions.items():
            vid = cur["current_version_id"]
            agreed_row = agreed.get(vid)
            reagreement_required = bool(cur["reagreement_required"])

            if agreed_row:
                agreed_at = agreed_row["agreed_at"]
                agreed_version_id = vid
                agreed_version = cur["current_version"]
                needs_reagreement = False
            else:
                if reagreement_required:
                    needs_reagreement = True
                    has_pending = True
                    agreed_at = None
                    agreed_version_id = None
                    agreed_version = None
                else:
                    cursor.execute("""
                        INSERT IGNORE INTO owner_terms_agreement (owner_id, term_version_id, agreed_at)
                        VALUES (%s, %s, %s)
                    """, (owner_id, vid, today))
                    conn.commit()
                    agreed_at = today
                    agreed_version_id = vid
                    agreed_version = cur["current_version"]
                    needs_reagreement = False

            terms_status.append({
                "term_id": term_id,
                "term_type": cur["term_type"],
                "title": cur["title"],
                "required": bool(cur["required"]),
                "current_version_id": vid,
                "current_version": cur["current_version"],
                "agreed_version_id": agreed_version_id,
                "agreed_version": agreed_version,
                "agreed_at": _date_serial(agreed_at),
                "needs_reagreement": needs_reagreement,
            })
        return {
            "owner_id": owner_id,
            "terms_status": terms_status,
            "has_pending_reagreement": has_pending,
        }
    finally:
        cursor.close()


def save_owner_agreements(
    conn, owner_id: int, agreements: List[Dict]
) -> Tuple[bool, Optional[str], int]:
    """사장님 약관 동의 저장. 필수 약관은 agreed=True 여야 함."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        today = date.today()
        cursor.execute("""
            SELECT t.id AS term_id, t.required, tv.id AS term_version_id
            FROM terms t
            INNER JOIN terms_version tv ON tv.term_id = t.id
            INNER JOIN (
                SELECT term_id, MAX(id) AS max_id FROM terms_version
                WHERE effective_date <= %s
                GROUP BY term_id
            ) latest ON latest.term_id = t.id AND latest.max_id = tv.id
            WHERE tv.effective_date <= %s AND t.target = 'owner'
        """, (today, today))
        current_map = {r["term_id"]: r for r in cursor.fetchall()}
        req_term_ids = {tid for tid, r in current_map.items() if r["required"]}

        by_term = {a["term_id"]: a for a in agreements}
        for term_id in req_term_ids:
            if term_id not in by_term or not by_term[term_id].get("agreed"):
                cursor.execute("SELECT title FROM terms WHERE id = %s", (term_id,))
                row = cursor.fetchone()
                title = row["title"] if row else "필수 약관"
                return False, f"필수 약관({title})에 동의해 주세요.", 0

        agreed_count = 0
        for a in agreements:
            term_id = a.get("term_id")
            term_version_id = a.get("term_version_id")
            agreed = a.get("agreed", False)
            if term_id not in current_map or current_map[term_id]["term_version_id"] != term_version_id:
                continue
            if not agreed:
                continue
            cursor.execute("""
                INSERT INTO owner_terms_agreement (owner_id, term_version_id, agreed_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE agreed_at = VALUES(agreed_at)
            """, (owner_id, term_version_id, today))
            agreed_count += 1
        conn.commit()
        return True, None, agreed_count
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cursor.close()


def get_owner_term_content_info(conn, term_type: str) -> Optional[Dict]:
    """
    사장님 약관 중 term_type에 해당하는 현재 시행 중인 최신 버전의 version 문자열 반환.
    반환: {"version": "260101"} 또는 None (해당 약관 없음)
    """
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        today = date.today()
        cursor.execute("""
            SELECT tv.version
            FROM terms t
            INNER JOIN terms_version tv ON tv.term_id = t.id
            INNER JOIN (
                SELECT term_id, MAX(id) AS max_id
                FROM terms_version
                WHERE effective_date <= %s
                GROUP BY term_id
            ) latest ON latest.term_id = t.id AND latest.max_id = tv.id
            WHERE tv.effective_date <= %s AND t.target = 'owner' AND t.term_type = %s
        """, (today, today, term_type))
        row = cursor.fetchone()
        return {"version": row["version"]} if row else None
    finally:
        cursor.close()


# ---------- Admin ----------

def create_term(conn, term_type: str, title: str, required: bool = True, target: str = "user") -> int:
    """약관 종류 추가. target: 'user' | 'owner'"""
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO terms (target, term_type, title, required) VALUES (%s, %s, %s, %s)",
            (target, term_type, title, required),
        )
        conn.commit()
        return cursor.lastrowid
    except pymysql.err.IntegrityError as e:
        conn.rollback()
        if e.args[0] == 1062:
            raise ValueError(f"이미 존재하는 약관입니다: target={target}, term_type={term_type}")
        raise
    finally:
        cursor.close()


def create_term_version(
    conn,
    term_id: int,
    version: str,
    notice_date: date,
    effective_date: date,
    reagreement_required: bool,
) -> int:
    """약관 버전 추가. effective_date >= notice_date + 30일 검증."""
    if effective_date < notice_date + timedelta(days=30):
        raise ValueError("시행일은 공지일로부터 30일 이후여야 합니다.")
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO terms_version (term_id, version, notice_date, effective_date, reagreement_required)
            VALUES (%s, %s, %s, %s, %s)
        """, (term_id, version, notice_date, effective_date, reagreement_required))
        conn.commit()
        return cursor.lastrowid
    except pymysql.err.IntegrityError as e:
        conn.rollback()
        if e.args[0] == 1062:
            raise ValueError(f"이미 존재하는 버전입니다: term_id={term_id}, version={version}")
        raise
    finally:
        cursor.close()


def get_term_version_id_by_version(conn, term_id: int, version: str) -> Optional[int]:
    """term_id + version에 해당하는 terms_version.id 반환. 없으면 None."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id FROM terms_version WHERE term_id = %s AND version = %s",
            (term_id, version),
        )
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()


def get_all_terms_with_versions(conn, target: Optional[str] = None) -> List[Dict]:
    """모든 약관 종류와 버전 목록 (관리자용). target=None이면 전체, 'user'|'owner'면 해당만."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        if target:
            cursor.execute(
                "SELECT id, target, term_type, title, required, created_at, updated_at FROM terms WHERE target = %s ORDER BY id",
                (target,),
            )
        else:
            cursor.execute("SELECT id, target, term_type, title, required, created_at, updated_at FROM terms ORDER BY target, id")
        terms = cursor.fetchall()
        cursor.execute("""
            SELECT id, term_id, version, notice_date, effective_date, reagreement_required, created_at, updated_at
            FROM terms_version ORDER BY term_id, id
        """)
        versions = cursor.fetchall()
        by_term = {}
        for t in terms:
            tid = t["id"]
            by_term[tid] = {
                "id": tid,
                "target": t.get("target", "user"),
                "term_type": t["term_type"],
                "title": t["title"],
                "required": bool(t["required"]),
                "created_at": _date_serial(t.get("created_at")),
                "updated_at": _date_serial(t.get("updated_at")),
                "versions": [],
            }
        term_ids = set(by_term.keys())
        for v in versions:
            tid = v["term_id"]
            if tid not in term_ids:
                continue
            by_term[tid]["versions"].append({
                "id": v["id"],
                "version": v["version"],
                "notice_date": _date_serial(v["notice_date"]),
                "effective_date": _date_serial(v["effective_date"]),
                "reagreement_required": bool(v["reagreement_required"]),
                "created_at": _date_serial(v.get("created_at")),
                "updated_at": _date_serial(v.get("updated_at")),
            })
        return list(by_term.values())
    finally:
        cursor.close()


def update_term_version(
    conn,
    version_id: int,
    version: Optional[str] = None,
    notice_date: Optional[date] = None,
    effective_date: Optional[date] = None,
    reagreement_required: Optional[bool] = None,
) -> bool:
    """약관 버전 수정. effective_date >= notice_date + 30일 유지."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute(
            "SELECT term_id, version, notice_date, effective_date FROM terms_version WHERE id = %s",
            (version_id,),
        )
        row = cursor.fetchone()
        if not row:
            return False
        n = notice_date if notice_date is not None else row["notice_date"]
        e = effective_date if effective_date is not None else row["effective_date"]
        if e < n + timedelta(days=30):
            raise ValueError("시행일은 공지일로부터 30일 이후여야 합니다.")
        updates = []
        values = []
        if version is not None:
            updates.append("version = %s")
            values.append(version)
        if notice_date is not None:
            updates.append("notice_date = %s")
            values.append(notice_date)
        if effective_date is not None:
            updates.append("effective_date = %s")
            values.append(effective_date)
        if reagreement_required is not None:
            updates.append("reagreement_required = %s")
            values.append(reagreement_required)
        if not updates:
            return True
        values.append(version_id)
        cursor.execute(
            f"UPDATE terms_version SET {', '.join(updates)} WHERE id = %s",
            tuple(values),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
