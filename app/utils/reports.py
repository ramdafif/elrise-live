from datetime import timedelta

from flask import abort, g

from app.db import query
from app.utils.validation import ValidationError, date_range, integer, text


def report_data(args):
    start, end = date_range(args)
    search = text(args, "q", "Pencarian", 100, False)
    status = args.get("status", "")
    if status not in {"", "present", "late", "absent", "leave", "off"}:
        raise ValidationError("Filter status tidak valid.")
    office_id = integer(args, "office_id", 1, 2147483647) if args.get("office_id") else None
    if office_id and not query("SELECT id FROM office_locations WHERE id=%s AND client_id=%s", (office_id, g.client["id"]), one=True):
        abort(404)
    sql = """SELECT e.*, o.name AS assigned_office, o.working_days FROM employees e
        LEFT JOIN office_locations o ON o.id=e.office_id AND o.client_id=e.client_id
        WHERE e.client_id=%s AND e.join_date<=%s AND (e.name LIKE %s OR e.employee_number LIKE %s)"""
    params = [g.client["id"], end, f"%{search}%", f"%{search}%"]
    if office_id:
        sql += " AND e.office_id=%s"
        params.append(office_id)
    employees = query(sql + " ORDER BY e.name,e.id LIMIT 5001", tuple(params))
    if len(employees) > 5000 or len(employees) * ((end - start).days + 1) > 60000:
        raise ValidationError("Laporan terlalu besar. Persempit tanggal, kantor, atau pencarian (maksimal 60.000 baris).")
    attendances = query("SELECT * FROM attendances WHERE client_id=%s AND work_date BETWEEN %s AND %s LIMIT 60001", (g.client["id"], start, end))
    leaves = query("SELECT employee_id,start_date,end_date FROM leave_requests WHERE client_id=%s AND status='approved' AND start_date<=%s AND end_date>=%s LIMIT 60001", (g.client["id"], end, start))
    if len(attendances) > 60000 or len(leaves) > 60000:
        raise ValidationError("Data tenant terlalu besar dalam periode ini. Persempit tanggal laporan.")
    attendance_map = {(row["employee_id"], row["work_date"]): row for row in attendances}
    leave_map = {}
    for leave in leaves:
        leave_map.setdefault(leave["employee_id"], []).append(leave)
    rows = []
    current = end
    while current >= start:
        for employee in employees:
            if employee["join_date"] > current:
                continue
            attendance = attendance_map.get((employee["id"], current))
            if not employee["is_active"] and not attendance:
                continue
            day_status = "absent"
            if attendance:
                day_status = attendance["status"]
            elif any(leave["start_date"] <= current <= leave["end_date"] for leave in leave_map.get(employee["id"], [])):
                day_status = "leave"
            elif str(current.isoweekday()) not in (employee["working_days"] or "1,2,3,4,5").split(","):
                day_status = "off"
            if status and status != day_status:
                continue
            rows.append({"employee": employee, "date": current, "status": day_status, "attendance": attendance})
        current -= timedelta(days=1)
    return rows, start, end
