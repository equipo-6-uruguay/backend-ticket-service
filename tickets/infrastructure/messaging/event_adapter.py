"""
Adaptador de eventos entrantes para el servicio de tickets.
"""
import logging
from typing import Dict, Any

from tickets.application.use_cases import DeleteTicketUseCase, DeleteTicketCommand
from tickets.infrastructure.repository import DjangoTicketRepository
from tickets.infrastructure.event_publisher import RabbitMQEventPublisher

logger = logging.getLogger(__name__)


class AssignmentEventAdapter:
    """
    Traduce eventos externos a casos de uso del dominio de Tickets.
    """
    def __init__(self):
        self.repository = DjangoTicketRepository()
        self.event_publisher = RabbitMQEventPublisher()

    def handle_assignment_deleted(self, event_data: Dict[str, Any]) -> None:
        """
        Maneja el evento assignment.deleted.
        Elimina el ticket asociado a la asignación.
        """
        ticket_id = event_data.get('ticket_id')
        
        if not ticket_id:
            logger.warning("Evento assignment.deleted sin ticket_id, ignorando")
            return
            
        try:
            ticket_id_int = int(ticket_id)
        except ValueError:
            logger.warning(f"ticket_id inválido en evento assignment.deleted: {ticket_id}")
            return
            
        use_case = DeleteTicketUseCase(self.repository, self.event_publisher)
        command = DeleteTicketCommand(ticket_id=ticket_id_int)
        
        try:
            use_case.execute(command)
            logger.info("Ticket %s eliminado exitosamente por evento assignment.deleted", ticket_id)
        except Exception as exc:
            # TicketNotFoundException es manejada aquí implícitamente si usamos Exception genérica,
            # pero lo ideal sería capturarla específicamente. Para mantener simpleza, logueamos.
            logger.error(
                "Error eliminando ticket %s por evento de asignación: %s",
                ticket_id,
                exc,
            )
