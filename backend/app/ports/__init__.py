"""Neutral capability contracts (ports).

Business layers (`shareddomain/`, `application/`) depend on these protocols
and delegate functions instead of importing `app.capabilities` directly.
Implementations live in the capability layer; the delegate functions here are
the composition points — swapping an implementation touches only the
corresponding capability module and this package.
"""
