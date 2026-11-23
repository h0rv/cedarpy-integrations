permit(principal, action, resource);

@id("block-user")
forbid(principal == ?principal, action, resource);
