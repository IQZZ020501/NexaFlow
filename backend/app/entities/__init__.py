"""Pure domain entities (non-persistent data classes).

This package is the Domain Entity layer of the data-isolation standard:
``app/domain/`` and ``app/shareddomain/*/models.py`` hold the SQLAlchemy
database models, repositories map between them, and business code must only
import entities from here. Entity fields mirror the database columns exactly
(including defaults) so mappers stay mechanical.
"""
