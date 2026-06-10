from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db, login_manager


# ──────────────────────────────────────────────
# 1. users
# ──────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relationships
    uploaded_files = db.relationship('ExcelFile', backref='uploader', lazy='dynamic',
                                     foreign_keys='ExcelFile.uploaded_by')
    permissions = db.relationship('UserRangePermission', backref='user', lazy='dynamic',
                                  foreign_keys='UserRangePermission.user_id')
    edits = db.relationship('EditHistory', backref='editor', lazy='dynamic',
                            foreign_keys='EditHistory.user_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ──────────────────────────────────────────────
# 2. excel_files
# ──────────────────────────────────────────────
class ExcelFile(db.Model):
    __tablename__ = 'excel_files'

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(256), nullable=False)
    stored_path = db.Column(db.String(512), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sheets = db.relationship('Sheet', backref='file', lazy='dynamic',
                             cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ExcelFile {self.display_name}>'


# ──────────────────────────────────────────────
# 3. sheets
# ──────────────────────────────────────────────
class Sheet(db.Model):
    __tablename__ = 'sheets'

    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey('excel_files.id'), nullable=False)
    sheet_name = db.Column(db.String(100), nullable=False)
    sheet_order = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    columns = db.relationship('SheetColumn', backref='sheet', lazy='dynamic',
                              cascade='all, delete-orphan')
    rows = db.relationship('SheetRow', backref='sheet', lazy='dynamic',
                           cascade='all, delete-orphan')
    permissions = db.relationship('UserRangePermission', backref='sheet', lazy='dynamic',
                                  cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Sheet {self.sheet_name}>'


# ──────────────────────────────────────────────
# 4. sheet_columns
# ──────────────────────────────────────────────
class SheetColumn(db.Model):
    __tablename__ = 'sheet_columns'

    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(db.Integer, db.ForeignKey('sheets.id'), nullable=False)
    column_key = db.Column(db.String(100), nullable=False)
    column_label = db.Column(db.String(200), nullable=False)
    column_order = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('sheet_id', 'column_order', name='uq_sheet_column_order'),
    )

    def __repr__(self):
        return f'<SheetColumn {self.column_label}>'


# ──────────────────────────────────────────────
# 5. sheet_rows
# ──────────────────────────────────────────────
class SheetRow(db.Model):
    __tablename__ = 'sheet_rows'

    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(db.Integer, db.ForeignKey('sheets.id'), nullable=False)
    row_order = db.Column(db.Integer, nullable=False)
    data = db.Column(db.JSON, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('sheet_id', 'row_order', name='uq_sheet_row_order'),
    )

    edits = db.relationship('EditHistory', backref='row', lazy='dynamic')

    def __repr__(self):
        return f'<SheetRow {self.row_order}>'


# ──────────────────────────────────────────────
# 6. user_range_permissions
# ──────────────────────────────────────────────
class UserRangePermission(db.Model):
    __tablename__ = 'user_range_permissions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sheet_id = db.Column(db.Integer, db.ForeignKey('sheets.id'), nullable=False)
    col_start = db.Column(db.Integer, nullable=False)
    col_end = db.Column(db.Integer, nullable=False)
    row_start = db.Column(db.Integer, nullable=False)
    row_end = db.Column(db.Integer, nullable=False)
    granted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relationships
    grantor = db.relationship('User', foreign_keys=[granted_by])

    def __repr__(self):
        return (f'<UserRangePermission user={self.user_id} '
                f'col=[{self.col_start},{self.col_end}] row=[{self.row_start},{self.row_end}]>')


# ──────────────────────────────────────────────
# 7. edit_history
# ──────────────────────────────────────────────
class EditHistory(db.Model):
    __tablename__ = 'edit_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sheet_id = db.Column(db.Integer, db.ForeignKey('sheets.id'), nullable=False)
    row_id = db.Column(db.Integer, db.ForeignKey('sheet_rows.id'))
    column_key = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    edited_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<EditHistory user={self.user_id} [{self.column_key}]>'


# ──────────────────────────────────────────────
# 8. user_edit_status — track who has finished editing
# ──────────────────────────────────────────────
class UserEditStatus(db.Model):
    __tablename__ = 'user_edit_status'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    file_id = db.Column(db.Integer, db.ForeignKey('excel_files.id'), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)

    user = db.relationship('User', foreign_keys=[user_id])
    file = db.relationship('ExcelFile', foreign_keys=[file_id])

    __table_args__ = (
        db.UniqueConstraint('user_id', 'file_id', name='uq_user_file_status'),
    )

    def __repr__(self):
        return f'<UserEditStatus user={self.user_id} file={self.file_id} done={self.is_completed}>'
