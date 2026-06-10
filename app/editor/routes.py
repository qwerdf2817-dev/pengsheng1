from datetime import datetime
from flask import render_template, jsonify, request, abort
from flask_login import login_required, current_user
from sqlalchemy.orm.attributes import flag_modified
from . import bp
from app.models import (
    ExcelFile, Sheet, SheetColumn, SheetRow,
    UserRangePermission, EditHistory, UserEditStatus,
    User,
)
from app.extensions import db


@bp.before_request
@login_required
def require_login():
    """All editor routes require login."""
    pass


# ──────────────────────────────────────────────
# File list — user's editable files
# ──────────────────────────────────────────────
@bp.route('/')
def file_list():
    # Show all active files (any user can view all files;
    # permissions are enforced per-sheet within the editor)
    files = ExcelFile.query.filter_by(is_active=True)\
        .order_by(ExcelFile.created_at.desc()).all()

    # Gather completion status per file for current user
    file_status_map = {}
    if current_user.is_authenticated:
        statuses = UserEditStatus.query.filter(
            UserEditStatus.user_id == current_user.id,
            UserEditStatus.file_id.in_([f.id for f in files])
        ).all() if files else []
        file_status_map = {s.file_id: s for s in statuses}

    # For each file, count total permitted users and completed users
    file_stats = {}
    for f in files:
        sheet_ids = [s.id for s in f.sheets]
        if sheet_ids:
            permitted_count = db.session.query(
                UserRangePermission.user_id
            ).filter(
                UserRangePermission.sheet_id.in_(sheet_ids)
            ).distinct().count()

            completed_count = UserEditStatus.query.filter(
                UserEditStatus.file_id == f.id,
                UserEditStatus.is_completed == True,
                UserEditStatus.user_id.in_(
                    db.session.query(UserRangePermission.user_id).filter(
                        UserRangePermission.sheet_id.in_(sheet_ids)
                    )
                )
            ).count()
        else:
            permitted_count = 0
            completed_count = 0

        my_status = file_status_map.get(f.id)
        file_stats[f.id] = {
            'permitted_count': permitted_count,
            'completed_count': completed_count,
            'my_completed': my_status.is_completed if my_status else False,
        }

    return render_template('editor/file_list.html', files=files, file_stats=file_stats)


# ──────────────────────────────────────────────
# Editor page
# ──────────────────────────────────────────────
@bp.route('/editor/<int:file_id>')
def editor_page(file_id):
    file_record = ExcelFile.query.get_or_404(file_id)
    sheets = Sheet.query.filter_by(file_id=file_id)\
        .order_by(Sheet.sheet_order).all()
    return render_template('editor/editor.html', file=file_record, sheets=sheets)


# ──────────────────────────────────────────────
# API: Get sheet data + permissions
# ──────────────────────────────────────────────
@bp.route('/api/sheet/<int:sheet_id>/data')
def sheet_data(sheet_id):
    sheet = Sheet.query.get_or_404(sheet_id)

    # Columns
    cols = SheetColumn.query.filter_by(sheet_id=sheet_id)\
        .order_by(SheetColumn.column_order).all()
    column_labels = [c.column_label for c in cols]
    column_keys = [c.column_key for c in cols]

    # Rows
    rows = SheetRow.query.filter_by(sheet_id=sheet_id)\
        .order_by(SheetRow.row_order).all()
    row_data = []
    for r in rows:
        d = r.data if isinstance(r.data, dict) else {}
        # Build ordered array matching columns
        row_array = [d.get(key, '') for key in column_keys]
        row_data.append(row_array)

    # Permissions: admin has full access; normal users need explicit grants
    if current_user.is_admin:
        row_count = len(row_data)
        col_count = len(column_labels)
        permissions = [{
            'col_start': 0,
            'col_end': col_count - 1,
            'row_start': 0,
            'row_end': row_count - 1,
        }] if row_count > 0 and col_count > 0 else []
    else:
        perms = UserRangePermission.query.filter_by(
            user_id=current_user.id, sheet_id=sheet_id
        ).all()
        permissions = [{
            'col_start': p.col_start,
            'col_end': p.col_end,
            'row_start': p.row_start,
            'row_end': p.row_end,
        } for p in perms]

    return jsonify({
        'columns': column_labels,
        'column_keys': column_keys,
        'rows': row_data,
        'permissions': permissions,
    })


# ──────────────────────────────────────────────
# API: Save cell changes
# ──────────────────────────────────────────────
@bp.route('/api/sheet/<int:sheet_id>/save', methods=['POST'])
def save_changes(sheet_id):
    sheet = Sheet.query.get_or_404(sheet_id)
    data = request.get_json()

    if not data or 'changes' not in data:
        return jsonify({'ok': False, 'error': '无效的请求数据'}), 400

    changes = data['changes']

    # Load column keys
    cols = SheetColumn.query.filter_by(sheet_id=sheet_id)\
        .order_by(SheetColumn.column_order).all()
    column_keys = [c.column_key for c in cols]

    # Load user permissions (admin bypasses check)
    if current_user.is_admin:
        perms = []
        is_admin = True
    else:
        perms = UserRangePermission.query.filter_by(
            user_id=current_user.id, sheet_id=sheet_id
        ).all()
        is_admin = False

    # Load all rows for this sheet
    rows = SheetRow.query.filter_by(sheet_id=sheet_id)\
        .order_by(SheetRow.row_order).all()

    # Validate each change
    for change in changes:
        row_idx = change.get('row')
        col_idx = change.get('col')
        new_value = change.get('new_value', '')

        if row_idx is None or col_idx is None:
            return jsonify({'ok': False, 'error': '缺少 row 或 col'}), 400

        # Check permission (admin skips)
        if not is_admin and not _has_permission(perms, row_idx, col_idx):
            return jsonify({
                'ok': False,
                'error': f'没有权限编辑 [{row_idx},{col_idx}] 单元格'
            }), 403

        # Update row data
        if row_idx >= len(rows):
            return jsonify({'ok': False, 'error': f'行 {row_idx} 不存在'}), 400

        if col_idx >= len(column_keys):
            return jsonify({'ok': False, 'error': f'列 {col_idx} 不存在'}), 400

        row = rows[row_idx]
        col_key = column_keys[col_idx]

        # Ensure data is dict
        if not isinstance(row.data, dict):
            row.data = {}

        old_value = row.data.get(col_key, '')

        # Write new value
        row.data[col_key] = str(new_value)
        flag_modified(row, 'data')  # Ensure SQLAlchemy detects the in-place JSON mutation

        # Record edit history
        history = EditHistory(
            user_id=current_user.id,
            sheet_id=sheet_id,
            row_id=row.id,
            column_key=col_key,
            old_value=str(old_value) if old_value else '',
            new_value=str(new_value),
        )
        db.session.add(history)

    db.session.commit()
    return jsonify({'ok': True})


def _has_permission(perms, row, col):
    """Check if (row, col) falls within any of the user's permitted ranges."""
    for p in perms:
        if p.col_start <= col <= p.col_end and p.row_start <= row <= p.row_end:
            return True
    return False


# ──────────────────────────────────────────────
# API: Confirm editing complete
# ──────────────────────────────────────────────
@bp.route('/api/file/<int:file_id>/confirm', methods=['POST'])
def confirm_complete(file_id):
    """Mark current user's editing as complete for this file."""
    file_record = ExcelFile.query.get_or_404(file_id)

    # Check user has any permission on this file
    sheet_ids = [s.id for s in file_record.sheets]
    has_permission = UserRangePermission.query.filter(
        UserRangePermission.user_id == current_user.id,
        UserRangePermission.sheet_id.in_(sheet_ids)
    ).first() is not None

    if not has_permission and not current_user.is_admin:
        return jsonify({'ok': False, 'error': '你在此表格中没有可编辑区域'}), 403

    # Create or update status
    status = UserEditStatus.query.filter_by(
        user_id=current_user.id, file_id=file_id
    ).first()

    if not status:
        status = UserEditStatus(
            user_id=current_user.id,
            file_id=file_id,
        )
        db.session.add(status)

    status.is_completed = True
    status.completed_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'ok': True, 'message': '已确认修改完毕'})


# ──────────────────────────────────────────────
# API: Get completion status for a file
# ──────────────────────────────────────────────
@bp.route('/api/file/<int:file_id>/status')
def file_status(file_id):
    """Get edit completion status for all users of this file."""
    file_record = ExcelFile.query.get_or_404(file_id)

    # Find all users who have permissions on this file
    sheet_ids = [s.id for s in file_record.sheets]
    user_perm_rows = db.session.query(
        UserRangePermission.user_id
    ).filter(
        UserRangePermission.sheet_id.in_(sheet_ids)
    ).distinct().all()

    permitted_user_ids = set(r[0] for r in user_perm_rows)

    # Get all permitted users
    permitted_users = User.query.filter(User.id.in_(permitted_user_ids)).all() if permitted_user_ids else []

    # Get edit statuses
    statuses = UserEditStatus.query.filter(
        UserEditStatus.file_id == file_id,
        UserEditStatus.user_id.in_(permitted_user_ids)
    ).all() if permitted_user_ids else []
    status_map = {s.user_id: s for s in statuses}

    users_status = []
    for user in permitted_users:
        st = status_map.get(user.id)
        users_status.append({
            'user_id': user.id,
            'username': user.username,
            'is_completed': st.is_completed if st else False,
            'completed_at': st.completed_at.strftime('%Y-%m-%d %H:%M') if (st and st.completed_at) else None,
        })

    # Sort: incomplete first, then by username
    users_status.sort(key=lambda u: (u['is_completed'], u['username']))

    # Current user's own status
    my_status = status_map.get(current_user.id)
    my_completed = my_status.is_completed if my_status else False

    return jsonify({
        'users': users_status,
        'my_completed': my_completed,
        'total': len(users_status),
        'completed_count': sum(1 for u in users_status if u['is_completed']),
    })
