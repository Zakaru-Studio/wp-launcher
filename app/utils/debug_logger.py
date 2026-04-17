#!/usr/bin/env python3
"""
Shim de compatibilité pour l'ancien ``SimpleDebugLogger``.

Ce module délègue désormais à ``app.utils.logger`` (source unique de vérité)
afin de supprimer la duplication entre les deux systèmes de logging.
Les callers historiques qui font ::

    from app.utils.debug_logger import create_debug_logger
    logger = create_debug_logger("my_project")
    logger.step("HELLO")

continuent à fonctionner sans modification.

Nouveaux callers : préférer ``from app.utils.logger import get_operation_logger``.
"""

import warnings

from app.utils.logger import OperationLogger, get_operation_logger

# Ré-export pour les éventuels imports directs de la classe.
# On garde le nom ``SimpleDebugLogger`` pour ne pas casser d'import legacy.
SimpleDebugLogger = OperationLogger


def create_debug_logger(project_name, operation_name="create"):
    """
    Factory legacy. Retourne un ``OperationLogger`` configuré pour l'opération
    demandée (par défaut ``create``, ce qui préserve le chemin de log
    historique ``logs/create/<project>_<timestamp>.log``).

    Accepte aussi ``create_debug_logger(operation, project)`` pour compat future.
    """
    warnings.warn(
        "app.utils.debug_logger.create_debug_logger est déprécié ; "
        "utilisez app.utils.logger.get_operation_logger à la place.",
        DeprecationWarning,
        stacklevel=2,
    )
    return get_operation_logger(operation_name=operation_name, project_name=project_name)


__all__ = ["create_debug_logger", "SimpleDebugLogger"]
