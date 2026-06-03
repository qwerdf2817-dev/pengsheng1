from flask import Blueprint

bp = Blueprint('editor', __name__)

from . import routes  # noqa
