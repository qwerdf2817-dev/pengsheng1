from flask_wtf import FlaskForm
from wtforms import StringField, FileField, SubmitField, HiddenField
from wtforms.validators import DataRequired


class UploadForm(FlaskForm):
    display_name = StringField('表格名称', validators=[DataRequired(message='请输入表格名称')])
    file = FileField('选择 Excel 文件', validators=[DataRequired(message='请选择文件')])
    submit = SubmitField('上传')


class PermissionForm(FlaskForm):
    """Form for adding a single range permission."""
    user_id = HiddenField('用户ID', validators=[DataRequired()])
    sheet_id = HiddenField('工作表ID', validators=[DataRequired()])
    col_start = HiddenField(validators=[DataRequired()])
    col_end = HiddenField(validators=[DataRequired()])
    row_start = HiddenField(validators=[DataRequired()])
    row_end = HiddenField(validators=[DataRequired()])
    submit = SubmitField('保存权限')
