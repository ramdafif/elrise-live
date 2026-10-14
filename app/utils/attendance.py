from app.db import query
from app.migrations import correction_schema_ready

ATTENDANCE_COLUMNS = (
    "id", "client_id", "employee_id", "office_id", "work_date", "status", "late_minutes",
    "office_name", "office_latitude", "office_longitude", "office_radius_m", "office_max_accuracy_m",
    "scheduled_start", "scheduled_end", "check_in_at", "check_in_latitude", "check_in_longitude",
    "check_in_accuracy", "check_in_distance", "check_in_device_at", "check_in_photo", "check_out_at",
    "check_out_latitude", "check_out_longitude", "check_out_accuracy", "check_out_distance",
    "check_out_device_at", "check_out_photo",
)

def attendance_source():
    if not correction_schema_ready():
        return """(SELECT a.*,NULL AS correction_id,a.check_in_at AS original_check_in_at,
            a.check_out_at AS original_check_out_at FROM attendances a)"""
    latest = """SELECT c.* FROM attendance_corrections c WHERE c.status='approved' AND NOT EXISTS (
        SELECT 1 FROM attendance_corrections newer WHERE newer.client_id=c.client_id
        AND newer.employee_id=c.employee_id AND newer.work_date=c.work_date
        AND newer.status='approved' AND newer.id>c.id)"""
    corrected = {key: f"COALESCE(c.{key},a.{key})" for key in
        ("office_id", "office_name", "scheduled_start", "scheduled_end", "late_minutes")}
    corrected.update(check_in_at="COALESCE(c.proposed_check_in_at,a.check_in_at)",
        check_out_at="COALESCE(c.proposed_check_out_at,a.check_out_at)",
        status="CASE WHEN c.id IS NULL THEN a.status WHEN c.late_minutes>0 THEN 'late' ELSE 'present' END")
    original_columns = ",".join(f"{corrected.get(key, 'a.' + key)} AS {key}" for key in ATTENDANCE_COLUMNS)
    synthetic = {key: "c." + key for key in ("client_id", "employee_id", "office_id", "work_date",
        "late_minutes", "office_name", "scheduled_start", "scheduled_end")}
    synthetic.update(check_in_at="c.proposed_check_in_at", check_out_at="c.proposed_check_out_at",
        status="CASE WHEN c.late_minutes>0 THEN 'late' ELSE 'present' END")
    synthetic_columns = ",".join(f"{synthetic.get(key, 'NULL')} AS {key}" for key in ATTENDANCE_COLUMNS)
    match = "a.client_id=c.client_id AND a.employee_id=c.employee_id AND a.work_date=c.work_date"
    return f"""(SELECT {original_columns},c.id AS correction_id,a.check_in_at AS original_check_in_at,
        a.check_out_at AS original_check_out_at FROM attendances a LEFT JOIN ({latest}) c ON {match}
        UNION ALL SELECT {synthetic_columns},c.id AS correction_id,NULL AS original_check_in_at,
        NULL AS original_check_out_at FROM ({latest}) c LEFT JOIN attendances a ON {match} WHERE a.id IS NULL)"""

def effective_record(client_id, employee_id, work_date):
    return query(f"SELECT * FROM {attendance_source()} effective WHERE client_id=%s AND employee_id=%s AND work_date=%s",
        (client_id, employee_id, work_date), one=True)
