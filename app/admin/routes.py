import os
import uuid
from flask import render_template, redirect, url_for, flash, request, current_app, send_file
from flask_login import login_required, current_user
from . import bp
from .forms import UploadForm, PermissionForm
from app.models import (
    User, ExcelFile, Sheet, SheetColumn, SheetRow,
    UserRangePermission, EditHistory, UserEditStatus,
)
from app.extensions import db
from utils.excel_io import import_excel, export_excel
from utils.decorators import admin_required


@bp.before_request
@login_required
@admin_required
def restrict_to_admin():
    """All routes in this blueprint require admin."""
    pass


# ──────────────────────────────────────────────
# Dashboard — file list
# ──────────────────────────────────────────────
@bp.route('/')
def dashboard():
    files = ExcelFile.query.filter_by(is_active=True)\
        .order_by(ExcelFile.created_at.desc()).all()

    # Gather completion stats per file
    file_status_stats = {}
    for f in files:
        sheet_ids = [s.id for s in f.sheets]
        if sheet_ids:
            permitted_users = db.session.query(
                UserRangePermission.user_id
            ).filter(
                UserRangePermission.sheet_id.in_(sheet_ids)
            ).distinct().all()
            permitted_ids = [r[0] for r in permitted_users]

            if permitted_ids:
                completed_count = UserEditStatus.query.filter(
                    UserEditStatus.file_id == f.id,
                    UserEditStatus.is_completed == True,
                    UserEditStatus.user_id.in_(permitted_ids)
                ).count()
                total = len(permitted_ids)

                # Get user details with status
                users_in_file = User.query.filter(User.id.in_(permitted_ids)).all()
                statuses = UserEditStatus.query.filter(
                    UserEditStatus.file_id == f.id,
                    UserEditStatus.user_id.in_(permitted_ids)
                ).all()
                status_map = {s.user_id: s for s in statuses}

                user_details = []
                for u in users_in_file:
                    st = status_map.get(u.id)
                    user_details.append({
                        'username': u.username,
                        'is_completed': st.is_completed if st else False,
                        'completed_at': st.completed_at.strftime('%m-%d %H:%M') if (st and st.completed_at) else None,
                    })
                user_details.sort(key=lambda x: (x['is_completed'], x['username']))
            else:
                completed_count = 0
                total = 0
                user_details = []
        else:
            completed_count = 0
            total = 0
            user_details = []

        file_status_stats[f.id] = {
            'total': total,
            'completed_count': completed_count,
            'user_details': user_details,
        }

    return render_template('admin/dashboard.html', files=files, file_status_stats=file_status_stats)


# ──────────────────────────────────────────────
# Upload Excel
# ──────────────────────────────────────────────
@bp.route('/upload', methods=['GET', 'POST'])
def upload():
    form = UploadForm()
    # Populate existing files for merge dropdown
    existing_files = ExcelFile.query.filter_by(is_active=True)\
        .order_by(ExcelFile.created_at.desc()).all()

    if form.validate_on_submit():
        merge_mode = request.form.get('merge_mode', 'new')
        target_file_id = request.form.get('target_file_id', type=int)

        # Save file to disk with unique name
        ext = os.path.splitext(form.file.data.filename)[1]
        unique_name = f'{uuid.uuid4().hex}{ext}'
        upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        stored_path = os.path.join(upload_dir, unique_name)

        # Save uploaded file to disk first
        form.file.data.save(stored_path)

        if merge_mode == 'merge' and target_file_id:
            # ── 合并模式：追加到已有表格 ──
            target_file = ExcelFile.query.get(target_file_id)
            if not target_file:
                flash('目标表格不存在', 'danger')
                return render_template('admin/upload.html', form=form, existing_files=existing_files)

            # Determine starting sheet order
            max_order = db.session.query(
                db.func.max(Sheet.sheet_order)
            ).filter(Sheet.file_id == target_file.id).scalar()
            starting_order = (max_order or -1) + 1

            try:
                import_excel(stored_path, target_file, starting_sheet_order=starting_order)
                db.session.commit()
                flash(f'已将「{form.display_name.data}」合并到「{target_file.display_name}」', 'success')
            except Exception as e:
                db.session.rollback()
                if os.path.exists(stored_path):
                    os.remove(stored_path)
                flash(f'合并失败：{str(e)}', 'danger')
                return render_template('admin/upload.html', form=form, existing_files=existing_files)
        else:
            # ── 新建模式 ──
            file_record = ExcelFile(
                display_name=form.display_name.data,
                original_filename=form.file.data.filename,
                stored_path=stored_path,
                uploaded_by=current_user.id,
            )
            db.session.add(file_record)
            db.session.flush()  # get file_record.id

            try:
                import_excel(stored_path, file_record)
                db.session.commit()
                flash(f'导入成功：{form.display_name.data}', 'success')
            except Exception as e:
                db.session.rollback()
                if os.path.exists(stored_path):
                    os.remove(stored_path)
                flash(f'导入失败：{str(e)}', 'danger')
                return render_template('admin/upload.html', form=form, existing_files=existing_files)

        return redirect(url_for('admin.dashboard'))

    return render_template('admin/upload.html', form=form, existing_files=existing_files)


# ──────────────────────────────────────────────
# Delete a file (soft-delete)
# ──────────────────────────────────────────────
@bp.route('/file/<int:file_id>/delete', methods=['POST'])
def delete_file(file_id):
    file_record = ExcelFile.query.get_or_404(file_id)
    file_record.is_active = False
    db.session.commit()
    flash(f'已删除：{file_record.display_name}', 'info')
    return redirect(url_for('admin.dashboard'))


# ──────────────────────────────────────────────
# Export file as Excel
# ──────────────────────────────────────────────
@bp.route('/file/<int:file_id>/export')
def export_file(file_id):
    file_record = ExcelFile.query.get_or_404(file_id)
    try:
        export_path = export_excel(file_record)
        return send_file(
            export_path,
            as_attachment=True,
            download_name=file_record.original_filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    except Exception as e:
        flash(f'导出失败：{str(e)}', 'danger')
        return redirect(url_for('admin.dashboard'))


# ──────────────────────────────────────────────
# User list (for assigning permissions)
# ──────────────────────────────────────────────
@bp.route('/users')
def user_list():
    users = User.query.order_by(User.created_at.desc()).all()
    files = ExcelFile.query.filter_by(is_active=True).order_by(ExcelFile.created_at.desc()).all()
    return render_template('admin/users.html', users=users, files=files)


# ──────────────────────────────────────────────
# Permission management page
# ──────────────────────────────────────────────
@bp.route('/permissions/<int:user_id>/<int:file_id>', methods=['GET', 'POST'])
def permissions(user_id, file_id):
    user = User.query.get_or_404(user_id)
    file_record = ExcelFile.query.get_or_404(file_id)
    sheets = Sheet.query.filter_by(file_id=file_id).order_by(Sheet.sheet_order).all()

    if request.method == 'POST':
        # Save permissions from AJAX
        sheet_id = request.form.get('sheet_id', type=int)
        col_start = request.form.get('col_start', type=int)
        col_end = request.form.get('col_end', type=int)
        row_start = request.form.get('row_start', type=int)
        row_end = request.form.get('row_end', type=int)

        # Validate
        if None in (sheet_id, col_start, col_end, row_start, row_end):
            return {'ok': False, 'error': '参数不完整'}, 400

        perm = UserRangePermission(
            user_id=user_id,
            sheet_id=sheet_id,
            col_start=col_start,
            col_end=col_end,
            row_start=row_start,
            row_end=row_end,
            granted_by=current_user.id,
        )
        db.session.add(perm)
        db.session.commit()
        return {'ok': True, 'id': perm.id}

    # GET — load existing permissions for this user
    all_permissions = {}
    for sheet in sheets:
        perms = UserRangePermission.query.filter_by(
            user_id=user_id, sheet_id=sheet.id
        ).all()
        all_permissions[sheet.id] = [{
            'id': p.id,
            'col_start': p.col_start,
            'col_end': p.col_end,
            'row_start': p.row_start,
            'row_end': p.row_end,
        } for p in perms]

    # Also get column info for rendering
    sheet_cols = {}
    for sheet in sheets:
        cols = SheetColumn.query.filter_by(sheet_id=sheet.id)\
            .order_by(SheetColumn.column_order).all()
        sheet_cols[sheet.id] = [{'key': c.column_key, 'label': c.column_label} for c in cols]

    return render_template(
        'admin/permissions.html',
        user=user,
        file=file_record,
        sheets=sheets,
        permissions=all_permissions,
        sheet_cols=sheet_cols,
    )


# ──────────────────────────────────────────────
# Delete a permission
# ──────────────────────────────────────────────
@bp.route('/permissions/<int:perm_id>/delete', methods=['POST'])
def delete_permission(perm_id):
    perm = UserRangePermission.query.get_or_404(perm_id)
    db.session.delete(perm)
    db.session.commit()
    return {'ok': True}


# ──────────────────────────────────────────────
# View edit history (all files, or specific file)
# ──────────────────────────────────────────────
@bp.route('/history')
@bp.route('/history/<int:file_id>')
def history(file_id=None):
    if file_id:
        file_record = ExcelFile.query.get_or_404(file_id)
        sheets = Sheet.query.filter_by(file_id=file_id).all()
        sheet_ids = [s.id for s in sheets]
    else:
        # Global history — show latest records across all active files
        file_record = None
        active_file_ids = [f.id for f in ExcelFile.query.filter_by(is_active=True).all()]
        sheets = Sheet.query.filter(Sheet.file_id.in_(active_file_ids)).all()
        sheet_ids = [s.id for s in sheets]

    records = EditHistory.query.filter(EditHistory.sheet_id.in_(sheet_ids))\
        .order_by(EditHistory.edited_at.desc()).limit(500).all()

    # Build user lookup
    user_ids = set(r.user_id for r in records)
    users = {u.id: u.username for u in User.query.filter(User.id.in_(user_ids)).all()}

    # Build file/sheet lookup for global view
    sheet_map = {s.id: s for s in sheets}
    file_map = {f.id: f for f in ExcelFile.query.all()}

    return render_template(
        'admin/history.html',
        file=file_record,
        records=records,
        users=users,
        sheet_map=sheet_map,
        file_map=file_map,
    )
