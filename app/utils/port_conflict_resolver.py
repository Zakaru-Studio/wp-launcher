#!/usr/bin/env python3
"""
Shim de rétro-compatibilité — DEPRECATED.

La logique a été consolidée dans `app.utils.port_utils`. Ce module ne sert
qu'à ne pas casser les callers historiques qui font :
    from app.utils.port_conflict_resolver import PortConflictResolver
"""
import warnings

warnings.warn(
    "app.utils.port_conflict_resolver est deprecated ; importez depuis "
    "app.utils.port_utils à la place.",
    DeprecationWarning,
    stacklevel=2,
)

from app.utils.port_utils import (  # noqa: F401,E402
    PortConflictResolver,
    find_free_port_for_project,
    get_comprehensive_used_ports,
    get_project_port,
    get_used_ports,
    is_port_available,
    is_port_in_use,
    save_project_port,
)
