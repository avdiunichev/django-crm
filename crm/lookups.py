from django.db.backends.signals import connection_created
from django.db.models import CharField, Lookup, TextField
from django.dispatch import receiver


def _casefold(value):
    if value is None:
        return ""
    return str(value).casefold()


@receiver(connection_created, dispatch_uid="crm_register_unicode_casefold")
def register_unicode_casefold(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        connection.connection.create_function(
            "UNICODE_CASEFOLD",
            1,
            _casefold,
            deterministic=True,
        )


class UnicodeIContains(Lookup):
    """Case-insensitive substring lookup that also handles Cyrillic in SQLite."""

    lookup_name = "iunicodecontains"

    def as_sql(self, compiler, connection):
        if connection.vendor != "sqlite":
            standard_lookup = self.lhs.output_field.get_lookup("icontains")(
                self.lhs,
                self.rhs,
            )
            return compiler.compile(standard_lookup)

        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        sql = (
            f"INSTR(UNICODE_CASEFOLD(COALESCE({lhs}, '')), "
            f"UNICODE_CASEFOLD(COALESCE({rhs}, ''))) > 0"
        )
        return sql, [*lhs_params, *rhs_params]


CharField.register_lookup(UnicodeIContains)
TextField.register_lookup(UnicodeIContains)
