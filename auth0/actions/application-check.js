exports.onExecutePostLogin = async (event, api) => {
    const mcpAudience = 'https://cnpg-mcp.wat.im/mcp';

    // Log for debugging (check Auth0 logs to see this)
    console.log('Auth0 Action triggered');
    console.log('Client ID:', event.client.client_id);
    console.log('Client Name:', event.client.name);

    // Check multiple places for audience
    const requestedAudience = event.request?.query?.audience ||
                             event.transaction?.requested_authorization_details?.audience ||
                             (event.authorization?.audience ? event.authorization.audience[0] : null);

    console.log('Requested Audience:', requestedAudience);

    // Allow if requesting MCP API
    if (requestedAudience === mcpAudience) {
      console.log('MCP API access - allowing');
      return;
    }

    // Also allow if client name is "Claude" (DCR clients)
    if (event.client.name === 'Claude') {
      console.log('Claude client detected - allowing');
      return;
    }

    // For all other clients, check allowedClients
    const allowed = (event.user.app_metadata && Array.isArray(event.user.app_metadata.allowedClients))
      ? event.user.app_metadata.allowedClients
      : [];

    if (!allowed.includes(event.client.client_id)) {
      console.log('Client not in allowedClients - denying');
      api.access.deny('ACTION_BLOCKING: User not allowed for this application');
    }
  };
