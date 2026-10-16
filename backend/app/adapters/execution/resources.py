"""Conservative provisional sizes; production Kata measurements remain pending."""

RESOURCES = {
    "small": {"cpu": "1", "memory": "512Mi"},
    "standard": {"cpu": "1", "memory": "1Gi"},
    "heavy": {"cpu": "2", "memory": "2Gi"},
}


def request_profile(request):
    if request.get("shell") or request.get("skill") or request.get("artifact"):
        return "heavy"
    if request.get("command") or request.get("script") or request.get("mcp"):
        return "standard"
    return "small"


def warm_quotas(size):
    # Size is the deployment total, shared across the three resource pools.
    return {"standard": (size + 2) // 3, "heavy": (size + 1) // 3, "small": size // 3}
