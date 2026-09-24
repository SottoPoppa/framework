{% include "authorization/roles.dsl" %}
{% include "presentation/routes.dsl" %}

presentation:configuration := {
    "presentation_type": "rest_api";
    "cors_policy": {
        "enabled": false;
    };
    "security_and_waf": {
        "tls_enabled": true;
        "min_tls_version": "TLSv1.2";
        "enable_hsts": true;
        "csrf_protection": true
    };
    "authentication_guards": {
        "auth_required": false
    }
};

policies: {
    policy:GET_ALLOW_PATH := {
        effect:"allow";
        target: { action: "GET"; };
        description:"Allow GET method for resources in guest role"; 
        condition: (@resource in roles.guest.resources) & (@action == "GET");
    };
    policy:GET_ALLOW_ALL := {
        effect:"allow";
        target: { action: "GET"; };
        description:"Allow all GET requests";
        condition: @action == "GET";
    };
    policy:POST_ALLOW_ALL := {
        effect:"allow";
        target: { action: "POST"; };
        description:"Allow all POST requests";
        condition: @action == "POST";
    };
}

rules : {
    "/": [policies.GET_ALLOW_ALL];
    "/chat": [policies.GET_ALLOW_ALL];
    "/shop": [policies.GET_ALLOW_ALL];
    "/profile": [policies.GET_ALLOW_PATH];
    "/login": [policies.GET_ALLOW_ALL,policies.POST_ALLOW_ALL];
    "/logout": [policies.GET_ALLOW_PATH, policies.POST_ALLOW_ALL];
    "/signup": [policies.GET_ALLOW_ALL,policies.POST_ALLOW_ALL];
    "/recovery": [policies.GET_ALLOW_ALL,policies.POST_ALLOW_ALL];
    "/admin": [policies.GET_ALLOW_PATH];
    "/browse": [policies.GET_ALLOW_ALL];
    "/home": [policies.GET_ALLOW_ALL];
    "/user/{id}": [policies.GET_ALLOW_ALL];
    "/tris": [policies.GET_ALLOW_ALL];
    "/kanban": [policies.GET_ALLOW_ALL];
    "/static/js/dsl.js": [policies.GET_ALLOW_ALL];
    //"/404": [policies.GET_ALLOW_ALL];
}
