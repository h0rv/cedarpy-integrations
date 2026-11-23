permit(principal is User, action == Action::"export", resource == Service::"reports")
when { principal.can_export && context.stepped_up };

forbid(principal is User, action == Action::"export", resource == Service::"reports")
unless { context.stepped_up };
