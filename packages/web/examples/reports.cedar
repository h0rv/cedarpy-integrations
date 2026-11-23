permit(principal, action == Action::"export", resource == Service::"reports")
when { principal.can_export && context.stepped_up };

forbid(principal, action == Action::"export", resource)
unless { context.stepped_up };
