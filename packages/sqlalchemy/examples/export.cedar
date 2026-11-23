permit(principal is User, action == Action::"export", resource is Document)
when { resource.owner == principal || resource.state == "public" };

forbid(principal, action == Action::"export", resource is Document)
when { resource.state == "sealed" };

forbid(principal, action == Action::"export", resource is Document)
unless { context.stepped_up };
