"""Third-party authorization and bounded application API requests."""


class IntegrationProviderError(RuntimeError):
    def __init__(self, message, *, uncertain=False, unauthorized=False):
        super().__init__(message)
        self.uncertain = uncertain
        self.unauthorized = unauthorized


def authorization_url(provider, client_id, redirect_uri, state, verifier, scopes):
    from app.adapters.integrations.client import authorization_url as build

    return build(provider, client_id, redirect_uri, state, verifier, scopes)


async def register_public_client(provider, redirect_uri, scopes):
    from app.adapters.integrations.client import register_public_client as register

    return await register(provider, redirect_uri, scopes)


async def exchange_tokens(provider, client_id, client_secret, **values):
    from app.adapters.integrations.client import exchange_tokens as exchange

    return await exchange(provider, client_id, client_secret, **values)


async def device_authorization(action, credentials):
    from app.adapters.integrations.client import device_authorization as request

    return await request(action, credentials)


async def call_integration(provider, operation, arguments, credentials, request_id):
    from app.adapters.integrations.client import call_integration as request

    return await request(provider, operation, arguments, credentials, request_id)
