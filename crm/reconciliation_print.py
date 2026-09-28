from decimal import Decimal

from django.views.generic import DetailView

from .models import ReconciliationAct, ReconciliationActLine
from .views import FinanceAccessMixin, LoginRequiredMixin, _primary_document_numbers_for_reconciliation


class ReconciliationActPrintView(LoginRequiredMixin, FinanceAccessMixin, DetailView):
    """Printable bilateral reconciliation statement, independent from the CRM detail view."""

    model = ReconciliationAct
    template_name = "crm/reconciliation_act_print.html"
    context_object_name = "act"

    def get_queryset(self):
        return ReconciliationAct.objects.select_related("owner_company", "counterparty").prefetch_related(
            "lines__transportation",
            "lines__movement__payment",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        act = self.object
        for line in act.lines.all():
            line.primary_document_numbers = _primary_document_numbers_for_reconciliation(
                line.transportation, act.counterparty
            )
            # Counterparty data is the mirrored view of the same settlement movement.
            line.counterparty_debit = line.credit
            line.counterparty_credit = line.debit
            line.counterparty_description = line.description
        context.update(
            counterparty_opening_debit=max(-act.opening_balance, Decimal("0.00")),
            counterparty_opening_credit=max(act.opening_balance, Decimal("0.00")),
            our_opening_debit=max(act.opening_balance, Decimal("0.00")),
            our_opening_credit=max(-act.opening_balance, Decimal("0.00")),
            counterparty_closing_debit=max(-act.closing_balance, Decimal("0.00")),
            counterparty_closing_credit=max(act.closing_balance, Decimal("0.00")),
            our_closing_debit=max(act.closing_balance, Decimal("0.00")),
            our_closing_credit=max(-act.closing_balance, Decimal("0.00")),
        )
        return context
