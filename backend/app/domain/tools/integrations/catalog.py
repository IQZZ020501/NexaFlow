"""The installed capability surface is explicit and independent of credentials."""

from app.domain.tools.integrations.dida_catalog import DIDA_OPERATIONS
from app.domain.tools.integrations.feishu_catalog import FEISHU_OPERATIONS
from app.domain.tools.integrations.tencent_catalog import TENCENT_OPERATIONS

PROVIDERS = {
    "dida": {"name": "Dida365", "scopes": ["tasks:read", "tasks:write"]},
    "feishu": {"name": "Feishu", "scopes": []},
    "tencent_meeting": {"name": "Tencent Meeting", "scopes": []},
}


OPERATIONS = {
    "dida": DIDA_OPERATIONS,
    "feishu": FEISHU_OPERATIONS,
    "tencent_meeting": TENCENT_OPERATIONS,
}
