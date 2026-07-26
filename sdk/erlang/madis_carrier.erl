-module(madis_carrier).
-export([capabilities/2, pending_events/3, publish/3, ack/3, cdr/4, control_status/2, routing_rules/3, create_routing_rule/3, set_routing_rule_enabled/4, dialplans/3, create_dialplan/3, set_dialplan_enabled/4, update_dialplan/4, delete_dialplan/3]).

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
