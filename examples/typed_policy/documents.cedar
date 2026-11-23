permit(principal is User, action == Action::"read", resource is Document)
when { (resource.owner == principal || resource.state == "public") && resource.state != "sealed" };

forbid(principal is User, action == Action::"read", resource is Document)
when { resource.state == "sealed" };
