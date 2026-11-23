permit(principal is User, action == Action::"view", resource is Photo)
when { resource.owner == principal || resource.visibility == "public" };
