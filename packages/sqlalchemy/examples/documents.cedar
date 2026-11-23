permit(principal, action == Action::"read", resource is Document)
when { resource.owner == principal || resource.state == "public" };

forbid(principal, action == Action::"read", resource is Document)
when { resource.state == "sealed" };
