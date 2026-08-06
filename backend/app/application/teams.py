"""Team use cases (facade over the teams domain)."""

from app.shareddomain.teams.services import (
    create_team,
    delete_team_permanently,
    get_team,
    list_teams,
    update_team,
)

__all__ = [
    "create_team",
    "delete_team_permanently",
    "get_team",
    "list_teams",
    "update_team",
]
