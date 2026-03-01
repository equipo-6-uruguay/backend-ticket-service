"""
Handlers para eventos de RabbitMQ en el servicio de tickets.
"""
from typing import Dict, Any

from tickets.infrastructure.messaging.event_adapter import AssignmentEventAdapter


def handle_assignment_event(event_data: Dict[str, Any]) -> None:
    """
    Procesa eventos entrantes usando el adaptador de eventos.
    
    Args:
        event_data: Diccionario con los datos del evento
    """
    adapter = AssignmentEventAdapter()
    event_type = event_data.get('event_type', 'unknown')
    
    if event_type == 'assignment.deleted':
        adapter.handle_assignment_deleted(event_data)
    else:
        # Ignorar eventos que no nos interesan (el exchange es fanout, llegarán otros eventos)
        pass
