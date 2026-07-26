-module(madis_carrier).
-export([capabilities/2, pending_events/3, publish/3, ack/3, cdr/4, control_status/2, routing_rules/3, create_routing_rule/3, set_routing_rule_enabled/4, dialplans/3, create_dialplan/3, set_dialplan_enabled/4, update_dialplan/4, delete_dialplan/3, control_resources/3, control_resources/4, create_control_resource/4, update_control_resource/5, delete_control_resource/4, delete_control_resource/5, set_control_resource_enabled/5, validate_routing_rule/3, validate_dialplan/3]).

control_resource_allowed(Resource) -> lists:member(Resource, ["gateways", "routes", "dispatch-sets", "dispatch-members", "dids", "header-rules", "access-control", "security-bans", "ani-groups", "ani-ranges", "registrations", "registration-bindings", "cluster-nodes", "security-events"]).
control_resource_path(Resource) ->
    case control_resource_allowed(Resource) of
        true -> "/api/v1/control/resources/" ++ Resource;
        false -> exit({madis_invalid_resource, Resource})
    end.

request(Base, Token, Method, Path, Body) ->
    application:ensure_all_started(inets),
    Headers = [{"Authorization", "Bearer " ++ Token}, {"Accept", "application/json"}],
    Content = case Body of none -> []; Json -> [{"content-type", "application/json"}, {"content-length", integer_to_list(byte_size(Json))}] end,
    true = (Body =:= none orelse byte_size(Body) =< 65536),
    Req = case Body of none -> {Base ++ Path, Headers}; Json -> {Base ++ Path, Headers ++ Content, "application/json", Json} end,
    case httpc:request(Method, Req, [{timeout, 2000}], []) of
        {ok, {{_, Code, _}, _, Response}} when Code >= 200, Code < 300 -> Response;
        {ok, {{_, Code, _}, _, _}} -> exit({madis_http_error, Code});
        Error -> exit({madis_transport_error, Error})
    end.

capabilities(Base, Token) -> request(Base, Token, get, "/api/v1/capabilities", none).
pending_events(Base, Token, Limit) ->
    N = min(max(Limit, 1), 100), request(Base, Token, get, "/api/v1/billing/events?limit=" ++ integer_to_list(N), none).
publish(Base, Token, Json) -> request(Base, Token, post, "/api/v1/billing/events", Json).
ack(Base, Token, EventId) -> request(Base, Token, post, "/api/v1/billing/events/ack?event_id=" ++ uri_string:percent_encode(EventId, uri_string:urlchar_reserved()), none).
cdr(Base, Token, Limit, CallId) ->
    N = min(max(Limit, 1), 100),
    Suffix = case CallId of
        "" -> "";
        _ -> "&call_id=" ++ uri_string:percent_encode(CallId, uri_string:urlchar_reserved())
    end,
    request(Base, Token, get, "/api/v1/billing/cdr?limit=" ++ integer_to_list(N) ++ Suffix, none).
control_status(Base, Token) -> request(Base, Token, get, "/api/v1/control/status", none).
routing_rules(Base, Token, Limit) ->
    N = min(max(Limit, 1), 100), request(Base, Token, get, "/api/v1/control/routing-rules?limit=" ++ integer_to_list(N), none).
create_routing_rule(Base, Token, Json) -> request(Base, Token, post, "/api/v1/control/routing-rules", Json).
set_routing_rule_enabled(Base, Token, RuleId, Enabled) ->
    State = case Enabled of true -> "enable"; _ -> "disable" end,
    request(Base, Token, post, "/api/v1/control/routing-rules/" ++ integer_to_list(RuleId) ++ "/" ++ State, none).
dialplans(Base, Token, Limit) ->
    N = min(max(Limit, 1), 100), request(Base, Token, get, "/api/v1/control/dialplans?limit=" ++ integer_to_list(N), none).
create_dialplan(Base, Token, Json) -> request(Base, Token, post, "/api/v1/control/dialplans", Json).
set_dialplan_enabled(Base, Token, RuleId, Enabled) ->
    State = case Enabled of true -> "enable"; _ -> "disable" end,
    request(Base, Token, post, "/api/v1/control/dialplans/" ++ integer_to_list(RuleId) ++ "/" ++ State, none).
update_dialplan(Base, Token, RuleId, Json) ->
    request(Base, Token, put, "/api/v1/control/dialplans/" ++ integer_to_list(RuleId), Json).
delete_dialplan(Base, Token, RuleId) ->
    request(Base, Token, delete, "/api/v1/control/dialplans/" ++ integer_to_list(RuleId), none).

control_resources(Base, Token, Resource) ->
    control_resources(Base, Token, Resource, 100).
control_resources(Base, Token, Resource, Limit) ->
    N = min(max(Limit, 1), 100), request(Base, Token, get, control_resource_path(Resource) ++ "?limit=" ++ integer_to_list(N), none).
create_control_resource(Base, Token, Resource, Json) ->
    request(Base, Token, post, control_resource_path(Resource), Json).
update_control_resource(Base, Token, Resource, ResourceId, Json) ->
    request(Base, Token, put, control_resource_path(Resource) ++ "/" ++ integer_to_list(ResourceId), Json).
delete_control_resource(Base, Token, Resource, ResourceId) ->
    delete_control_resource(Base, Token, Resource, ResourceId, "").
delete_control_resource(Base, Token, Resource, ResourceId, Revision) ->
    Suffix = case Revision of "" -> ""; _ -> "?expected_revision=" ++ uri_string:percent_encode(Revision, uri_string:urlchar_reserved()) end,
    request(Base, Token, delete, control_resource_path(Resource) ++ "/" ++ integer_to_list(ResourceId) ++ Suffix, none).
set_control_resource_enabled(Base, Token, Resource, ResourceId, Enabled) ->
    State = case Enabled of true -> "enable"; _ -> "disable" end,
    request(Base, Token, post, control_resource_path(Resource) ++ "/" ++ integer_to_list(ResourceId) ++ "/" ++ State, none).

validate_routing_rule(Base, Token, Json) ->
    request(Base, Token, post, "/api/v1/control/validate/routing-rule", Json).
validate_dialplan(Base, Token, Json) ->
    request(Base, Token, post, "/api/v1/control/validate/dialplan", Json).
