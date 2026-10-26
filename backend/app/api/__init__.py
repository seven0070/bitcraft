"""
API路由模块
"""

from flask import Blueprint

graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)
decision_bp = Blueprint('decision', __name__)
minecraft_bp = Blueprint('minecraft', __name__)

from . import graph  # noqa: E402, F401
from . import simulation  # noqa: E402, F401
from . import report  # noqa: E402, F401
from . import decision  # noqa: E402, F401
from . import minecraft  # noqa: E402, F401

