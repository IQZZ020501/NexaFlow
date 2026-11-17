"""Bounded OAuth transport; providers never receive business-host credentials."""


class OAuthExchangeError(RuntimeError):
    pass


async def validate_oauth_endpoint(url, *, allow_private=False):
    from app.adapters.oauth.client import validate_endpoint

    return await validate_endpoint(url, allow_private=allow_private)


async def oauth_post(
    url,
    data,
    *,
    client_auth="none",
    client_id="",
    client_secret="",
    allow_private=False,
):
    from app.adapters.oauth.client import post

    return await post(
        url,
        data,
        client_auth=client_auth,
        client_id=client_id,
        client_secret=client_secret,
        allow_private=allow_private,
    )
